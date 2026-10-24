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

    max_continuous_hours = float(get_runtime_setting("max_continuous_run_hours", 12.0))
    auto_stop_on_sched = bool(get_runtime_setting("auto_stop_on_schedule_end", True))
    enforce_schedule = bool(get_runtime_setting("enforce_work_schedule", True))
    notify_heartbeat = bool(get_runtime_setting("notify_running_heartbeat", True))
    heartbeat_interval_hours = float(get_runtime_setting("heartbeat_interval_hours", 4.0))

    for run in active_runs:
        gen = run.generator
        if not gen:
            continue

        elapsed_seconds = max(1, int((current_time - run.start_time).total_seconds()))
        elapsed_hours = elapsed_seconds / 3600.0

        # Find active maintenance schedule
        m_sched = next((m for m in gen.maintenance_schedules if m.is_active), None)

        # -------------------------------------------------------------
        # 1. Guardrail: Empty Tank Protection / Max Continuous Run (> 12h)
        # -------------------------------------------------------------
        if elapsed_hours >= max_continuous_hours:
            run.end_time = current_time
            run.duration_seconds = elapsed_seconds
            run.duration_hours = round(elapsed_hours, 2)
            consumed_l = round(run.duration_hours * gen.nominal_consumption_l_per_h, 2)
            run.calculated_consumption_l = consumed_l
            run.end_hours = round(run.start_hours + run.duration_hours, 2)
            gen.current_operating_hours = run.end_hours
            gen.fuel_tank_level_l = round(max(0.0, gen.fuel_tank_level_l - consumed_l), 2)
            run.end_fuel_level_l = gen.fuel_tank_level_l

            if m_sched and gen.current_operating_hours >= m_sched.next_due_hours:
                gen.status = "MAINTENANCE_REQUIRED"
            else:
                gen.status = "STOPPED"

            run.status = "COMPLETED"
            run.note = f"Аварійна автоматична зупинка: спрацював захист від порожнього бака (перевищено ліміт {max_continuous_hours:.0f} год безперервної роботи)"

            await log_audit(
                db=db,
                action="GENERATOR_SAFETY_STOP",
                entity_type="Generator",
                entity_id=str(gen.id),
                user_id=run.user_id,
                details={
                    "reason": "MAX_CONTINUOUS_RUN_EXCEEDED",
                    "max_hours": max_continuous_hours,
                    "elapsed_hours": run.duration_hours,
                    "run_id": run.id,
                    "end_hours": run.end_hours,
                    "fuel_level": gen.fuel_tank_level_l
                }
            )

            await send_push_notification(
                db=db,
                title=f"🚨 Аварійна зупинка — {gen.name}",
                body=f"Генератор автоматично зупинено після {run.duration_hours:.1f} год безперервної роботи (захист від порожнього бака та перегріву).",
                event_type="GENERATOR_SAFETY_STOP",
                generator_id=gen.id,
                facility_id=gen.facility_id,
                url="/?tab=tab-dashboard"
            )

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
                            elapsed_hours=run.duration_hours,
                            fuel_level=gen.fuel_tank_level_l,
                            db=db
                        )
                except Exception as mail_exc:
                    print(f"[EMAIL] Notice: safety stop email dispatch note: {mail_exc}", flush=True)

            await db.commit()
            results["safety_stopped_max_run"] += 1
            continue

        # -------------------------------------------------------------
        # 2. Guardrail: Work Schedule End Auto-Stop (Strictly Day Shift)
        # -------------------------------------------------------------
        if auto_stop_on_sched and enforce_schedule:
            schedules_data = [
                {"weekday": s.weekday, "start_time": s.start_time, "end_time": s.end_time, "is_active": s.is_active}
                for s in (gen.schedules or [])
            ]
            is_allowed, sched_msg = is_within_work_schedule(schedules_data, dt=current_time)
            if not is_allowed:
                run.end_time = current_time
                run.duration_seconds = elapsed_seconds
                run.duration_hours = round(elapsed_hours, 2)
                consumed_l = round(run.duration_hours * gen.nominal_consumption_l_per_h, 2)
                run.calculated_consumption_l = consumed_l
                run.end_hours = round(run.start_hours + run.duration_hours, 2)
                gen.current_operating_hours = run.end_hours
                gen.fuel_tank_level_l = round(max(0.0, gen.fuel_tank_level_l - consumed_l), 2)
                run.end_fuel_level_l = gen.fuel_tank_level_l

                if m_sched and gen.current_operating_hours >= m_sched.next_due_hours:
                    gen.status = "MAINTENANCE_REQUIRED"
                else:
                    gen.status = "STOPPED"

                run.status = "COMPLETED"
                run.note = f"Автоматична зупинка за розкладом закінчення робочого дня: {sched_msg}"

                await log_audit(
                    db=db,
                    action="GENERATOR_AUTO_STOP",
                    entity_type="Generator",
                    entity_id=str(gen.id),
                    user_id=run.user_id,
                    details={
                        "reason": "WORK_SCHEDULE_ENDED",
                        "schedule_reason": sched_msg,
                        "elapsed_hours": run.duration_hours,
                        "run_id": run.id,
                        "end_hours": run.end_hours,
                        "fuel_level": gen.fuel_tank_level_l
                    }
                )

                await send_push_notification(
                    db=db,
                    title=f"⏱️ Автозупинка за графіком — {gen.name}",
                    body=f"Робочий день завершено ({sched_msg}). Генератор автоматично зупинено. Напрацювання за сеанс: {run.duration_hours:.2f} год.",
                    event_type="GENERATOR_AUTO_STOP",
                    generator_id=gen.id,
                    facility_id=gen.facility_id,
                    url="/?tab=tab-dashboard"
                )

                await db.commit()
                results["auto_stopped_schedule"] += 1
                continue

        # -------------------------------------------------------------
        # 3. Guardrail: 4-Hour Heartbeat Reminder ('Генератор досі працює?')
        # -------------------------------------------------------------
        if notify_heartbeat and elapsed_hours >= heartbeat_interval_hours:
            # Check if heartbeat was already sent recently for this generator during this run
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

            # Require at least (heartbeat_interval_hours - 0.1) hours since the last heartbeat
            cooldown_seconds = int((heartbeat_interval_hours - 0.1) * 3600)
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
                results["heartbeats_sent"] += 1

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
    if _LAST_WEEKLY_DIGEST_DATE == today_str:
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
        await send_weekly_digest_email(
            recipients=rec_list,
            excel_bytes=excel_bytes,
            period_label=period_label,
            summary_text="Щотижневий автоматичний звіт за розкладом.",
            db=db
        )
        _LAST_WEEKLY_DIGEST_DATE = today_str
        print(f"[EMAIL] Weekly digest email successfully dispatched to {rec_list}", flush=True)
        return True
    except Exception as exc:
        print(f"[EMAIL] Failed to send weekly digest email: {exc}", flush=True)
        return False

async def run_operational_guard_loop(interval_seconds: int = 30):
    """
    Background worker that runs every `interval_seconds` to enforce operational safeguards.
    """
    print(f"[GUARD] Operational guard loop started (interval: {interval_seconds}s).", flush=True)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            async with AsyncSessionLocal() as session:
                await check_operational_guardrails(session)
                await check_and_send_weekly_digest(session)
        except asyncio.CancelledError:
            print("[GUARD] Operational guard loop cancelled (shutdown).", flush=True)
            break
        except Exception as e:
            print(f"[GUARD] Error during guard loop check: {e}", flush=True)
