import asyncio
import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import AsyncSessionLocal
from backend.app.models.generator import Generator, GeneratorRun, GeneratorSchedule
from backend.app.models.maintenance import MaintenanceSchedule
from backend.app.models.notification import NotificationLog
from backend.app.core.timezone import now_utc, now_facility, is_within_work_schedule
from backend.app.models.user import User
from backend.app.services.settings_service import get_runtime_setting
from backend.app.services.audit_service import log_audit
from backend.app.services.notification_service import send_push_notification, check_and_notify_low_fuel, check_and_notify_maintenance_due
from backend.app.services.generator_service import stop_generator

# Guard health monitoring registry (OPG-18)
guard_health_status = {
    "is_running": False,
    "last_successful_check": None,
    "consecutive_failures": 0,
    "last_error": None
}


async def check_operational_guardrails(db: AsyncSession) -> Dict[str, Any]:
    """
    Checks running generators for operational safeguards:
    1. Maximum single session overrun fuse (> 12 hours) - empty tank protection.
    2. Working hours schedule auto-stop (strictly no night runs).
    3. Periodic heartbeat reminder every 4 hours ('Генератор досі працює?').
    """
    current_time = now_utc()
    results = {
        "auto_stopped_schedule": 0,
        "safety_stopped_max_run": 0,
        "heartbeats_sent": 0,
        "active_runs_checked": 0
    }

    # Query all active runs with generators, schedules, and maintenance schedules eagerly loaded
    q = (
        select(GeneratorRun)
        .options(
            selectinload(GeneratorRun.generator).selectinload(Generator.schedules),
            selectinload(GeneratorRun.generator).selectinload(Generator.maintenance_schedules)
        )
        .where(GeneratorRun.status == "RUNNING")
    )
    res = await db.execute(q)
    active_runs = res.scalars().all()
    results["active_runs_checked"] = len(active_runs)

    # Validate runtime settings with safe fallback bounds (OPG-04, OPG-12)
    try:
        max_continuous_hours = float(get_runtime_setting("max_continuous_run_hours", 12.0))
        if max_continuous_hours <= 0:
            max_continuous_hours = 12.0
    except Exception:
        max_continuous_hours = 12.0

    auto_stop_on_sched = bool(get_runtime_setting("auto_stop_on_schedule_end", True))
    enforce_schedule = bool(get_runtime_setting("enforce_work_schedule", True))
    notify_heartbeat = bool(get_runtime_setting("notify_running_heartbeat", True))

    try:
        heartbeat_interval_hours = float(get_runtime_setting("heartbeat_interval_hours", 4.0))
        if heartbeat_interval_hours < 0.5:
            heartbeat_interval_hours = 4.0
    except Exception:
        heartbeat_interval_hours = 4.0

    for run in active_runs:
        # OPG-09: Isolate errors per generator run so one failure does not halt check of others
        try:
            gen = run.generator
            if not gen:
                continue

            # Ensure run is still active
            if run.status != "RUNNING" or gen.status != "RUNNING":
                continue

            elapsed_seconds = max(1, int((current_time - run.start_time).total_seconds()))
            elapsed_hours = elapsed_seconds / 3600.0

            # -------------------------------------------------------------
            # 1. Guardrail: Empty Tank Protection / Max Continuous Run (> 12h)
            # OPG-01, OPG-03, OPG-07, OPG-08, OPG-19: Use unified stop_generator
            # -------------------------------------------------------------
            if elapsed_hours >= max_continuous_hours:
                note_text = f"Аварійна автоматична зупинка: спрацював захист від порожнього бака (перевищено ліміт {max_continuous_hours:.0f} год безперервної роботи)"
                stopped_run = await stop_generator(
                    db=db,
                    generator_id=gen.id,
                    user_id=None,
                    reason="MAX_CONTINUOUS_RUN_EXCEEDED",
                    system_note=note_text,
                    actor_type="SYSTEM_GUARD"
                )
                if stopped_run:
                    results["safety_stopped_max_run"] += 1
                    # Email notification for safety stop
                    if get_runtime_setting("email_notify_safety_stop", True) and get_runtime_setting("smtp_enabled", False):
                        try:
                            from backend.app.services.email_service import send_safety_stop_email
                            admin_res = await db.execute(select(User.email).where(User.is_superadmin == True, User.email.isnot(None)))
                            recipients = [e for e in admin_res.scalars().all() if e]
                            rec_setting = str(get_runtime_setting("email_weekly_recipients", "")).strip()
                            if rec_setting:
                                for r in rec_setting.replace(";", ",").split(","):
                                    r_clean = r.strip()
                                    if r_clean and r_clean not in recipients:
                                        recipients.append(r_clean)
                            if recipients:
                                await send_safety_stop_email(
                                    recipients=recipients,
                                    generator_name=gen.name,
                                    reason=f"Перевищено максимальний ліміт безперервної роботи ({max_continuous_hours:.0f} год). Захист від роботи насухо.",
                                    elapsed_hours=stopped_run.duration_hours,
                                    fuel_level=gen.fuel_tank_level_l,
                                    db=db
                                )
                        except Exception as mail_exc:
                            print(f"[EMAIL] Notice: safety stop email dispatch note: {mail_exc}", flush=True)
                continue

            # -------------------------------------------------------------
            # 2. Guardrail: Work Schedule End Auto-Stop (Strictly Day Shift)
            # OPG-01, OPG-07, OPG-08, OPG-19: Use unified stop_generator
            # -------------------------------------------------------------
            if auto_stop_on_sched and enforce_schedule:
                schedules_data = [
                    {"weekday": s.weekday, "start_time": s.start_time, "end_time": s.end_time, "is_active": s.is_active}
                    for s in (gen.schedules or [])
                ]
                is_allowed, sched_msg = is_within_work_schedule(schedules_data, dt=current_time)
                if not is_allowed:
                    note_text = f"Автоматична зупинка за розкладом закінчення робочого дня: {sched_msg}"
                    stopped_run = await stop_generator(
                        db=db,
                        generator_id=gen.id,
                        user_id=None,
                        reason="WORK_SCHEDULE_ENDED",
                        system_note=note_text,
                        actor_type="SYSTEM_GUARD"
                    )
                    if stopped_run:
                        results["auto_stopped_schedule"] += 1
                    continue

            # -------------------------------------------------------------
            # 3. Guardrail: Heartbeat Reminder ('Генератор досі працює?')
            # OPG-10, OPG-11: Ensure notification log commit
            # -------------------------------------------------------------
            if notify_heartbeat and elapsed_hours >= heartbeat_interval_hours:
                last_hb_q = (
                    select(NotificationLog.created_at)
                    .where(
                        and_(
                            NotificationLog.event_type == "GENERATOR_HEARTBEAT",
                            NotificationLog.generator_id == gen.id,
                            NotificationLog.created_at >= run.start_time
                        )
                    )
                    .order_by(NotificationLog.created_at.desc())
                    .limit(1)
                )
                last_hb_res = await db.execute(last_hb_q)
                last_hb_time = last_hb_res.scalar()

                cooldown_seconds = max(3600, int((heartbeat_interval_hours - 0.1) * 3600))
                should_send = (last_hb_time is None) or ((current_time - last_hb_time).total_seconds() >= cooldown_seconds)

                if should_send:
                    hours_int = int(elapsed_hours)
                    title = f"⚠️ Генератор {gen.name} досі працює ({hours_int} год)"
                    body = (
                        f"Генератор безперервно працює вже {elapsed_hours:.1f} год (з {run.start_time.strftime('%H:%M')}). "
                        f"Перевірте рівень палива (залишок: ~{gen.fuel_tank_level_l:.1f} л) та чи не забули його зупинити."
                    )

                    await send_push_notification(
                        db=db,
                        title=title,
                        body=body,
                        event_type="GENERATOR_HEARTBEAT",
                        generator_id=gen.id,
                        facility_id=gen.facility_id,
                        url="/?tab=tab-dashboard"
                    )
                    await db.commit()
                    results["heartbeats_sent"] += 1

            # -------------------------------------------------------------
            # 4. Live Low Fuel & Maintenance Due Checks During Active Run
            # -------------------------------------------------------------
            from backend.app.services.notification_service import (
                check_and_notify_low_fuel,
                check_and_notify_maintenance_due,
            )
            from backend.app.services.measurement_service import is_generator_in_measurement_mode
            nom_cons = float(gen.nominal_consumption_l_per_h or 0.0)
            est_consumed_l = elapsed_hours * nom_cons
            live_fuel_l = max(0.0, float(gen.fuel_tank_level_l or 0.0) - est_consumed_l)
            live_hours = float(gen.current_operating_hours or 0.0) + elapsed_hours
            if not await is_generator_in_measurement_mode(db, gen.id):
                await check_and_notify_low_fuel(db, gen, live_fuel_l)
            await check_and_notify_maintenance_due(db, gen.id, current_hours=live_hours)
        except Exception as run_err:
            print(f"[GUARD] Error processing generator run {getattr(run, 'id', None)}: {run_err}", flush=True)
            continue

    # Update health monitoring registry on successful check (OPG-18)
    guard_health_status["last_successful_check"] = now_utc().isoformat()
    guard_health_status["consecutive_failures"] = 0
    guard_health_status["last_error"] = None
    return results



_LAST_WEEKLY_DIGEST_DATE: Optional[str] = None


async def check_and_send_weekly_digest(db: AsyncSession) -> bool:
    global _LAST_WEEKLY_DIGEST_DATE
    if not get_runtime_setting("email_weekly_report_enabled", False):
        return False
    if not get_runtime_setting("smtp_enabled", False):
        return False

    recipients_str = str(get_runtime_setting("email_weekly_recipients", "")).strip()
    if not recipients_str:
        return False

    rec_list = [r.strip() for r in recipients_str.replace(";", ",").split(",") if r.strip()]
    if not rec_list:
        return False

    now_fac = now_facility()
    target_day = int(get_runtime_setting("email_weekly_send_day", 0))
    if now_fac.weekday() != target_day:
        return False

    target_time_str = str(get_runtime_setting("email_weekly_send_time", "08:00")).strip()
    today_str = now_fac.strftime("%Y-%m-%d")

    # 1. Check in-memory and runtime cache
    if _LAST_WEEKLY_DIGEST_DATE == today_str:
        return False
    if str(get_runtime_setting("last_weekly_digest_date", "")).strip() == today_str:
        _LAST_WEEKLY_DIGEST_DATE = today_str
        return False

    # 2. Check persistent DB state (survives container restarts, code reloads, VPS reboots)
    import json
    from sqlalchemy import func
    from backend.app.models.settings import SystemSetting
    from backend.app.services.settings_service import update_system_settings

    setting_res = await db.execute(
        select(SystemSetting.value_json).where(SystemSetting.key == "last_weekly_digest_date")
    )
    raw_setting_val = setting_res.scalar()
    if raw_setting_val:
        try:
            db_last_date = str(json.loads(raw_setting_val)).strip()
        except Exception:
            db_last_date = str(raw_setting_val).strip('" ')
        if db_last_date == today_str:
            _LAST_WEEKLY_DIGEST_DATE = today_str
            return False

    today_start_utc = now_fac.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(datetime.timezone.utc).replace(tzinfo=None)
    existing_log_res = await db.execute(
        select(func.count(NotificationLog.id)).where(
            and_(
                NotificationLog.event_type == "EMAIL_DIGEST_WEEKLY",
                NotificationLog.created_at >= today_start_utc,
                NotificationLog.success_count > 0
            )
        )
    )
    if (existing_log_res.scalar() or 0) > 0:
        _LAST_WEEKLY_DIGEST_DATE = today_str
        return False

    cur_time_str = now_fac.strftime("%H:%M")
    if cur_time_str < target_time_str:
        return False

    from backend.app.services.report_service import generate_excel_report
    from backend.app.services.email_service import send_weekly_digest_email

    try:
        target_fac = get_runtime_setting("email_weekly_facility_id") or get_runtime_setting("default_facility_id")
        target_gen = get_runtime_setting("email_weekly_generator_id") or get_runtime_setting("default_generator_id")
        excel_bytes = await generate_excel_report(db=db, facility_id=target_fac, generator_id=target_gen)
        week_ago = now_fac - datetime.timedelta(days=7)
        period_label = f"{week_ago.strftime('%d.%m.%Y')} — {now_fac.strftime('%d.%m.%Y')}"
        send_res = await send_weekly_digest_email(
            recipients=rec_list,
            excel_bytes=excel_bytes,
            period_label=period_label,
            summary_text="Щотижневий автоматичний звіт за розкладом.",
            db=db
        )
        if isinstance(send_res, dict) and send_res.get("status") == "error":
            print(f"[EMAIL] Weekly digest email failed to deliver: {send_res.get('error')}", flush=True)
            return False

        # Persist state to DB so container restarts on the same day never re-send the digest
        await update_system_settings(db, {"last_weekly_digest_date": today_str})
        db.add(NotificationLog(
            event_type="EMAIL_DIGEST_WEEKLY",
            facility_id=target_fac,
            generator_id=target_gen,
            title=f"📊 Щотижневий звіт роботи генераторів — {period_label}",
            body=f"Щотижневий автоматичний звіт за розкладом надіслано на: {', '.join(rec_list)}",
            recipients_count=len(rec_list),
            success_count=len(rec_list),
            failure_count=0
        ))
        await log_audit(
            db=db,
            action="WEEKLY_DIGEST_AUTO_SENT",
            entity_type="Report",
            entity_id=today_str,
            details={"recipients": rec_list, "period": period_label, "date": today_str}
        )
        await db.commit()

        _LAST_WEEKLY_DIGEST_DATE = today_str
        print(f"[EMAIL] Weekly digest email successfully dispatched to {rec_list}", flush=True)
        return True
    except Exception as exc:
        print(f"[EMAIL] Failed to send weekly digest email: {exc}", flush=True)
        return False

async def run_operational_guard_loop(interval_seconds: int = 30):
    """
    Background worker that runs every `interval_seconds` to enforce operational safeguards.
    Monitored via guard_health_status (OPG-18).
    """
    print(f"[GUARD] Operational guard loop started (interval: {interval_seconds}s).", flush=True)
    guard_health_status["is_running"] = True
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            async with AsyncSessionLocal() as session:
                await check_operational_guardrails(session)
                await check_and_send_weekly_digest(session)
        except asyncio.CancelledError:
            print("[GUARD] Operational guard loop cancelled (shutdown).", flush=True)
            guard_health_status["is_running"] = False
            break
        except Exception as e:
            guard_health_status["consecutive_failures"] += 1
            guard_health_status["last_error"] = str(e)
            print(f"[GUARD] Error during guard loop check: {e}", flush=True)
