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
from backend.app.core.timezone import now_utc, now_facility, to_facility_time, is_within_work_schedule
from backend.app.models.user import User
from backend.app.services.settings_service import get_runtime_setting
from backend.app.services.audit_service import log_audit
from backend.app.services.notification_service import send_push_notification, check_and_notify_low_fuel, check_and_notify_maintenance_due
from backend.app.services.generator_service import (
    stop_generator,
    WARMUP_NOTE_PREFIX,
    get_generators_idle_info_map,
)
from backend.app.services.fuel_service import compute_generator_live_fuel_l

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
        "warmup_done_sent": 0,
        "warmup_due_sent": 0,
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
                            from backend.app.services.email_service import (
                                resolve_facility_email_recipients,
                                send_safety_stop_email,
                            )
                            recipients = await resolve_facility_email_recipients(
                                db, facility_id=gen.facility_id, include_weekly_recipients=True
                            )
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
            # 2. Guardrail: Work Schedule End Auto-Stop / Outside Schedule Alert
            # OPG-01, OPG-07, OPG-08, OPG-19: Use unified stop_generator
            # -------------------------------------------------------------
            schedules_data = [
                {"weekday": s.weekday, "start_time": s.start_time, "end_time": s.end_time, "is_active": s.is_active}
                for s in (gen.schedules or [])
            ]
            if enforce_schedule:
                is_allowed, sched_msg = is_within_work_schedule(
                    schedules_data, dt=current_time, tz_name=gen.timezone
                )
                if not is_allowed:
                    if auto_stop_on_sched:
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
                            if get_runtime_setting("email_notify_safety_stop", True) and get_runtime_setting("smtp_enabled", False):
                                try:
                                    from backend.app.services.email_service import (
                                        resolve_facility_email_recipients,
                                        send_schedule_auto_stop_email,
                                    )
                                    recipients = await resolve_facility_email_recipients(
                                        db, facility_id=gen.facility_id, include_weekly_recipients=True
                                    )
                                    if recipients:
                                        await send_schedule_auto_stop_email(
                                            recipients=recipients,
                                            generator_name=gen.name,
                                            schedule_msg=sched_msg,
                                            elapsed_hours=stopped_run.duration_hours,
                                            fuel_level=gen.fuel_tank_level_l,
                                            db=db,
                                        )
                                except Exception as mail_exc:
                                    print(f"[EMAIL] Notice: schedule auto-stop email dispatch note: {mail_exc}", flush=True)
                        continue
                    else:
                        from backend.app.services.notification_service import notify_outside_work_hours
                        await notify_outside_work_hours(
                            db=db,
                            generator=gen,
                            schedule_msg=sched_msg,
                            context_text=f"Генератор працює {elapsed_hours:.1f} год поза робочим графіком (автостоп вимкнено).",
                        )

            # Обчислюємо живі показники витрати пального та мотогодин для активного циклу
            live_fuel_l = compute_generator_live_fuel_l(gen, run, now_dt=current_time, clamp_zero=True)
            live_hours = float(gen.current_operating_hours or 0.0) + elapsed_hours

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
                    start_local = to_facility_time(run.start_time, tz_name=gen.timezone)
                    title = f"⚠️ Генератор {gen.name} досі працює ({hours_int} год)"
                    body = (
                        f"Генератор безперервно працює вже {elapsed_hours:.1f} год (з {start_local.strftime('%H:%M')}). "
                        f"Перевірте рівень палива (залишок: ~{live_fuel_l:.1f} л) та чи не забули його зупинити."
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
            # 3.1 Preventive Warmup Completion Reminder
            # -------------------------------------------------------------
            if str(run.note or "").startswith(WARMUP_NOTE_PREFIX):
                try:
                    warmup_minutes = max(5, int(get_runtime_setting("warmup_duration_minutes", 15)))
                except Exception:
                    warmup_minutes = 15
                if elapsed_seconds >= warmup_minutes * 60:
                    warmup_done_q = (
                        select(NotificationLog.id)
                        .where(
                            and_(
                                NotificationLog.event_type == "GENERATOR_WARMUP_DONE",
                                NotificationLog.generator_id == gen.id,
                                NotificationLog.created_at >= run.start_time,
                            )
                        )
                        .limit(1)
                    )
                    if (await db.execute(warmup_done_q)).scalar() is None:
                        elapsed_mins = int(elapsed_seconds // 60)
                        await send_push_notification(
                            db=db,
                            title=f"🔥 Профілактичний прогрів завершено — {gen.name}",
                            body=(
                                f"Генератор пропрацював {elapsed_mins} хв (план: {warmup_minutes} хв). "
                                f"Перевірте роботу та зупиніть обладнання."
                            ),
                            event_type="GENERATOR_WARMUP_DONE",
                            generator_id=gen.id,
                            facility_id=gen.facility_id,
                            url="/?tab=tab-dashboard",
                        )
                        await db.commit()
                        results["warmup_done_sent"] += 1

            # -------------------------------------------------------------
            # 4. Live Low Fuel & Maintenance Due Checks During Active Run
            # -------------------------------------------------------------
            from backend.app.services.notification_service import (
                check_and_notify_low_fuel,
                check_and_notify_maintenance_due,
            )
            from backend.app.services.measurement_service import is_generator_in_measurement_mode
            if not await is_generator_in_measurement_mode(db, gen.id):
                await check_and_notify_low_fuel(db, gen, live_fuel_l)
            await check_and_notify_maintenance_due(db, gen.id, current_hours=live_hours)
        except Exception as run_err:
            print(f"[GUARD] Error processing generator run {getattr(run, 'id', None)}: {run_err}", flush=True)
            continue

    # -------------------------------------------------------------
    # 5. Preventive Warmup Idle Check for Stopped Generators
    # -------------------------------------------------------------
    results["warmup_due_sent"] = await _check_preventive_warmup_due_notifications(db, current_time)

    # Update health monitoring registry on successful check (OPG-18)
    guard_health_status["last_successful_check"] = now_utc().isoformat()
    guard_health_status["consecutive_failures"] = 0
    guard_health_status["last_error"] = None
    return results


async def _check_preventive_warmup_due_notifications(
    db: AsyncSession,
    current_time: datetime.datetime,
) -> int:
    """Надсилає сповіщення про необхідність профілактичного прогріву при тривалому простої."""
    if not bool(get_runtime_setting("warmup_reminder_enabled", True)):
        return 0
    try:
        warmup_minutes = max(5, int(get_runtime_setting("warmup_duration_minutes", 15)))
        cold_temp_c = float(get_runtime_setting("warmup_cold_temp_c", -10.0))
        trigger_mode = str(get_runtime_setting("warmup_trigger_mode", "any") or "any").lower()
        if trigger_mode not in ("any", "idle", "cold", "both"):
            trigger_mode = "any"
    except Exception:
        warmup_minutes, cold_temp_c, trigger_mode = 15, -10.0, "any"

    gens_res = await db.execute(
        select(Generator).where(
            Generator.is_active == True,  # noqa: E712
            Generator.is_configured == True,  # noqa: E712
            Generator.status.notin_(["RUNNING", "FAULTY", "BLOCKED"]),
        )
    )
    stopped_gens = list(gens_res.scalars().all())
    if not stopped_gens:
        return 0

    facility_temps: Dict[int, Optional[float]] = {}
    if trigger_mode in ("any", "cold", "both"):
        from backend.app.services.weather_service import get_facility_weather
        unique_fids = {int(g.facility_id) for g in stopped_gens if g.facility_id is not None}
        for fid in unique_fids:
            try:
                w = await get_facility_weather(db, fid)
                if w and w.get("is_available") and w.get("temp_c") is not None:
                    facility_temps[fid] = float(w["temp_c"])
                else:
                    facility_temps[fid] = None
            except Exception:
                facility_temps[fid] = None

    idle_map = await get_generators_idle_info_map(db, stopped_gens)
    sent_count = 0
    for gen in stopped_gens:
        info = idle_map.get(gen.id, {})
        if info.get("warmup_recently_done"):
            continue
        idle_due = bool(info.get("warmup_recommended"))
        cur_temp = facility_temps.get(int(gen.facility_id)) if gen.facility_id is not None else None
        cold_due = bool(cur_temp is not None and cur_temp <= cold_temp_c)

        if trigger_mode == "idle":
            should_notify = idle_due
        elif trigger_mode == "cold":
            should_notify = cold_due
        elif trigger_mode == "both":
            should_notify = idle_due and cold_due
        else:
            should_notify = idle_due or cold_due

        if not should_notify:
            continue
        last_activity_at = info.get("last_run_at") or gen.created_at
        if last_activity_at is not None and last_activity_at.tzinfo is not None:
            last_activity_at = last_activity_at.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        last_due_q = (
            select(NotificationLog.created_at)
            .where(
                and_(
                    NotificationLog.event_type == "GENERATOR_WARMUP_DUE",
                    NotificationLog.generator_id == gen.id,
                )
            )
            .order_by(NotificationLog.created_at.desc())
            .limit(1)
        )
        last_due_at = (await db.execute(last_due_q)).scalar()
        if last_due_at is not None and last_due_at.tzinfo is not None:
            last_due_at = last_due_at.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        if last_due_at is not None:
            since_notif = (current_time - last_due_at).total_seconds()
            notified_after_last_run = (last_activity_at is None) or (last_due_at >= last_activity_at)
            if notified_after_last_run and since_notif < 7 * 86400:
                continue

        days_idle = int(info.get("days_since_last_run") or 0)
        reasons = []
        if idle_due:
            reasons.append(f"не запускався вже {days_idle} дн.")
        if cold_due and cur_temp is not None:
            reasons.append(f"температура на об'єкті {cur_temp:.0f}°C (поріг ≤ {cold_temp_c:.0f}°C)")
        reason_text = "Генератор " + " та ".join(reasons) + "."
        await send_push_notification(
            db=db,
            title=f"🔥 Потрібен профілактичний прогрів — {gen.name}",
            body=(
                f"{reason_text} "
                f"Рекомендовано провести {warmup_minutes}-хвилинний прогрів для збереження АКБ та паливної системи."
            ),
            event_type="GENERATOR_WARMUP_DUE",
            generator_id=gen.id,
            facility_id=gen.facility_id,
            url="/?tab=tab-dashboard",
        )
        await db.commit()
        sent_count += 1
    return sent_count



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
    if rec_list:
        opted_out_res = await db.execute(
            select(User.email).where(
                User.email_notifications_enabled == False,  # noqa: E712
                User.email.isnot(None),
            )
        )
        opted_out_set = {e.strip().lower() for e in opted_out_res.scalars().all() if e}
        rec_list = [r for r in rec_list if r.lower() not in opted_out_set]
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
