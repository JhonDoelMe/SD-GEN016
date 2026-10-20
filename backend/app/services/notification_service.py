import json
import base64
import datetime
import asyncio
from typing import Dict, Any, Optional, Tuple, List
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from py_vapid import Vapid
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import pywebpush

from backend.app.models.settings import SystemSetting
from backend.app.models.notification import PushSubscription, NotificationLog
from backend.app.models.generator import Generator
from backend.app.models.maintenance import MaintenanceSchedule
from backend.app.services.settings_service import get_runtime_setting, set_runtime_setting
from backend.app.core.timezone import now_facility


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


async def get_or_create_vapid_keys(db: AsyncSession) -> Tuple[str, str, str]:
    """Retrieve existing VAPID keys from system_settings or generate and persist new ones."""
    q = select(SystemSetting).where(SystemSetting.key.in_(["vapid_public_key", "vapid_private_key_pem", "vapid_claims_sub"]))
    res = await db.execute(q)
    rows = {r.key: r.value_json for r in res.scalars().all()}

    pub_b64 = rows.get("vapid_public_key")
    priv_pem = rows.get("vapid_private_key_pem")
    sub_claim = rows.get("vapid_claims_sub") or "mailto:maxiuallc@gmail.com"

    if pub_b64 and priv_pem:
        # Strip quotes if stored as JSON string
        try:
            pub_clean = json.loads(pub_b64)
        except Exception:
            pub_clean = pub_b64
        try:
            priv_clean = json.loads(priv_pem)
        except Exception:
            priv_clean = priv_pem
        return pub_clean, priv_clean, sub_claim

    # Generate new VAPID EC P-256 keys
    vapid = Vapid()
    vapid.generate_keys()
    raw_pub = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    new_pub_b64 = base64.urlsafe_b64encode(raw_pub).decode("ascii").rstrip("=")
    new_priv_pem = vapid.private_pem().decode("utf-8")

    # Persist in database
    db.add(SystemSetting(key="vapid_public_key", value_json=json.dumps(new_pub_b64), description="VAPID Web Push Public Key (base64url)"))
    db.add(SystemSetting(key="vapid_private_key_pem", value_json=json.dumps(new_priv_pem), description="VAPID Web Push Private Key (PEM)"))
    if "vapid_claims_sub" not in rows:
        db.add(SystemSetting(key="vapid_claims_sub", value_json=json.dumps(sub_claim), description="VAPID Web Push Subject Claim"))
    await db.commit()

    return new_pub_b64, new_priv_pem, sub_claim


async def get_vapid_public_key(db: AsyncSession) -> str:
    pub_b64, _, _ = await get_or_create_vapid_keys(db)
    return pub_b64


async def subscribe_device(
    db: AsyncSession,
    user_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: Optional[str] = None,
    facility_id: Optional[int] = None
) -> PushSubscription:
    q = select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    res = await db.execute(q)
    sub = res.scalars().first()

    now = utc_now()
    if sub:
        sub.user_id = user_id
        sub.facility_id = facility_id
        sub.p256dh = p256dh
        sub.auth = auth
        sub.user_agent = user_agent
        sub.is_active = True
        sub.updated_at = now
    else:
        sub = PushSubscription(
            user_id=user_id,
            facility_id=facility_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            is_active=True,
            created_at=now,
            updated_at=now
        )
        db.add(sub)

    await db.commit()
    await db.refresh(sub)
    return sub


async def unsubscribe_device(db: AsyncSession, endpoint: str) -> bool:
    q = select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    res = await db.execute(q)
    sub = res.scalars().first()
    if sub:
        sub.is_active = False
        sub.updated_at = utc_now()
        await db.commit()
        return True
    return False


async def get_notification_settings_data(db: AsyncSession) -> Dict[str, Any]:
    pub_key = await get_vapid_public_key(db)

    # Count active subscriptions
    q_count = select(func.count(PushSubscription.id)).where(PushSubscription.is_active == True)
    count_res = await db.execute(q_count)
    active_count = count_res.scalar() or 0

    return {
        "notifications_enabled": bool(get_runtime_setting("notifications_enabled", True)),
        "notify_generator_start": bool(get_runtime_setting("notify_generator_start", True)),
        "notify_generator_stop": bool(get_runtime_setting("notify_generator_stop", True)),
        "notify_low_fuel": bool(get_runtime_setting("notify_low_fuel", True)),
        "low_fuel_threshold_l": float(get_runtime_setting("low_fuel_threshold_l", 5.0)),
        "notify_maintenance": bool(get_runtime_setting("notify_maintenance", True)),
        "max_maintenance_notifications_per_day": int(get_runtime_setting("max_maintenance_notifications_per_day", 2)),
        "notify_critical_faults": bool(get_runtime_setting("notify_critical_faults", True)),
        "vapid_public_key": pub_key,
        "active_subscriptions_count": active_count
    }


def _send_single_webpush_sync(sub_info: Dict[str, Any], payload_str: str, vapid_obj: Vapid, claims: Dict[str, str]) -> Tuple[bool, bool]:
    """
    Synchronous WebPush sender executed in threadpool.
    Returns: (success: bool, is_expired: bool)
    """
    try:
        pywebpush.webpush(
            subscription_info=sub_info,
            data=payload_str,
            vapid_private_key=vapid_obj,
            vapid_claims=claims,
            ttl=3600
        )
        return True, False
    except pywebpush.WebPushException as ex:
        status_code = getattr(getattr(ex, "response", None), "status_code", None)
        print(f"[WEBPUSH] WebPushException (status={status_code}): {ex}", flush=True)
        # Only 404 or 410 mean the subscription is definitively expired or unsubscribed
        if status_code in (404, 410):
            return False, True
        return False, False
    except Exception as ex:
        print(f"[WEBPUSH] Unexpected error sending push: {ex}", flush=True)
        return False, False


async def send_push_notification(
    db: AsyncSession,
    title: str,
    body: str,
    event_type: str,
    generator_id: Optional[int] = None,
    facility_id: Optional[int] = None,
    url: str = "/"
) -> Dict[str, Any]:
    """
    Dispatches a push notification to all subscribed devices with anti-spam guards,
    strict rate limiting (e.g. maintenance <= 2 per day), and persistent logging.
    """
    # 1. Check global notifications enabled
    if not get_runtime_setting("notifications_enabled", True):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "Сповіщення вимкнено в налаштуваннях"}

    # 2. Check event-specific toggles
    event_toggle_map = {
        "GENERATOR_START": "notify_generator_start",
        "GENERATOR_STOP": "notify_generator_stop",
        "LOW_FUEL": "notify_low_fuel",
        "MAINTENANCE_DUE": "notify_maintenance",
        "CRITICAL_FAULT": "notify_critical_faults",
    }
    toggle_key = event_toggle_map.get(event_type)
    if toggle_key and not get_runtime_setting(toggle_key, True):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": f"Тип сповіщення {event_type} вимкнено"}

    now = utc_now()

    # 3. Rate limiting for MAINTENANCE_DUE (strictly <= max_maintenance_notifications_per_day, default 2)
    if event_type == "MAINTENANCE_DUE" and generator_id:
        max_daily = int(get_runtime_setting("max_maintenance_notifications_per_day", 2))
        # Start of current calendar day in facility timezone
        fac_now = now_facility()
        today_start_fac = fac_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_fac.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        # Count maintenance notifications sent today for this generator
        q_count = select(func.count(NotificationLog.id)).where(
            and_(
                NotificationLog.event_type == "MAINTENANCE_DUE",
                NotificationLog.generator_id == generator_id,
                NotificationLog.created_at >= today_start_utc
            )
        )
        res_count = await db.execute(q_count)
        today_count = res_count.scalar() or 0
        if today_count >= max_daily:
            return {
                "sent": 0,
                "failed": 0,
                "skipped": True,
                "reason": f"Денний ліміт нагадувань про ТО ({max_daily} на добу) для цього генератора вже досягнуто"
            }

        # Also prevent back-to-back spam: require at least 3 hours since the last notification
        q_last = select(NotificationLog.created_at).where(
            and_(
                NotificationLog.event_type == "MAINTENANCE_DUE",
                NotificationLog.generator_id == generator_id
            )
        ).order_by(NotificationLog.created_at.desc()).limit(1)
        res_last = await db.execute(q_last)
        last_time = res_last.scalar()
        if last_time and (now - last_time).total_seconds() < 10800:  # 3 hours
            return {
                "sent": 0,
                "failed": 0,
                "skipped": True,
                "reason": "Нагадування про ТО було надіслано менше 3 годин тому"
            }

    # 4. Rate limiting for LOW_FUEL (cooldown: 3 hours)
    if event_type == "LOW_FUEL" and generator_id:
        q_last_fuel = select(NotificationLog.created_at).where(
            and_(
                NotificationLog.event_type == "LOW_FUEL",
                NotificationLog.generator_id == generator_id
            )
        ).order_by(NotificationLog.created_at.desc()).limit(1)
        res_fuel = await db.execute(q_last_fuel)
        last_fuel_time = res_fuel.scalar()
        if last_fuel_time and (now - last_fuel_time).total_seconds() < 10800:  # 3 hours
            return {
                "sent": 0,
                "failed": 0,
                "skipped": True,
                "reason": "Сповіщення про низький рівень палива вже надсилалося нещодавно"
            }

    # 5. Fetch active subscriptions (with User eagerly loaded)
    sub_query = select(PushSubscription).options(selectinload(PushSubscription.user)).where(PushSubscription.is_active == True)
    sub_res = await db.execute(sub_query)
    all_active = sub_res.scalars().all()

    # Routing rules:
    # - Admins and SuperAdmins ALWAYS receive start, stop, critical fault, low fuel and maintenance notifications!
    # - Other roles (e.g. operators) receive notifications matching their facility or global.
    subscriptions = []
    seen_endpoints = set()
    for s in all_active:
        if s.endpoint in seen_endpoints:
            continue
        user = s.user
        if not user or not user.is_active:
            continue

        is_admin_or_super = user.is_superadmin or any(r.name.lower() in ("admin", "superadmin") for r in (user.roles or []))
        if is_admin_or_super:
            subscriptions.append(s)
            seen_endpoints.add(s.endpoint)
        elif not facility_id or s.facility_id is None or s.facility_id == facility_id:
            subscriptions.append(s)
            seen_endpoints.add(s.endpoint)

    if not subscriptions:
        # Log notification attempt even with 0 subscribers
        log_entry = NotificationLog(
            event_type=event_type,
            generator_id=generator_id,
            facility_id=facility_id,
            title=title,
            body=body,
            recipients_count=0,
            success_count=0,
            failure_count=0,
            created_at=now
        )
        db.add(log_entry)
        await db.commit()
        return {"sent": 0, "failed": 0, "recipients": 0}

    # 6. Prepare VAPID keys and payload
    pub_b64, priv_pem, sub_claim = await get_or_create_vapid_keys(db)
    claims = {"sub": sub_claim}

    try:
        vapid_obj = Vapid.from_pem(priv_pem.encode("utf-8"))
    except Exception:
        vapid_obj = Vapid.from_string(priv_pem)

    payload = json.dumps({
        "title": title,
        "body": body,
        "icon": "/frontend/icons/icon-192.png",
        "badge": "/frontend/icons/icon-192.png",
        "data": {"url": url, "event_type": event_type},
        "tag": f"sd-{event_type.lower()}"
    })

    success_count = 0
    failure_count = 0
    expired_sub_ids = []

    for s in subscriptions:
        sub_info = {
            "endpoint": s.endpoint,
            "keys": {
                "p256dh": s.p256dh,
                "auth": s.auth
            }
        }
        ok, is_expired = await asyncio.to_thread(_send_single_webpush_sync, sub_info, payload, vapid_obj, claims)
        if ok:
            success_count += 1
        else:
            failure_count += 1
            if is_expired:
                expired_sub_ids.append(s.id)

    # Deactivate ONLY subscriptions explicitly rejected with 404/410 by push service
    if expired_sub_ids:
        for sid in expired_sub_ids:
            for s in subscriptions:
                if s.id == sid:
                    s.is_active = False
                    s.updated_at = now

    # 7. Record notification log
    log_entry = NotificationLog(
        event_type=event_type,
        generator_id=generator_id,
        facility_id=facility_id,
        title=title,
        body=body,
        recipients_count=len(subscriptions),
        success_count=success_count,
        failure_count=failure_count,
        created_at=now
    )
    db.add(log_entry)
    await db.commit()

    return {
        "sent": success_count,
        "failed": failure_count,
        "recipients": len(subscriptions)
    }


# High-level trigger helpers

async def notify_generator_start(
    db: AsyncSession,
    generator: Generator,
    user_name: str,
    start_fuel: float,
    start_hours: float
):
    title = f"🟢 Запуск генератора — {generator.name}"
    body = f"Оператор: {user_name}. Мотогодини: {start_hours:.1f} год. Рівень у баку: {start_fuel:.1f} л."
    await send_push_notification(
        db=db,
        title=title,
        body=body,
        event_type="GENERATOR_START",
        generator_id=generator.id,
        facility_id=generator.facility_id,
        url="/?tab=tab-dashboard"
    )


async def notify_generator_stop(
    db: AsyncSession,
    generator: Generator,
    user_name: str,
    duration_str: str,
    consumption_l: Optional[float],
    end_fuel: Optional[float]
):
    cons_str = f"{consumption_l:.2f} л" if consumption_l is not None else "розраховується"
    fuel_str = f"{end_fuel:.1f} л" if end_fuel is not None else "-"
    title = f"🔴 Зупинка генератора — {generator.name}"
    body = f"Оператор: {user_name}. Відпрацьовано: {duration_str}. Витрата: {cons_str}. Залишок у баку: {fuel_str}."
    await send_push_notification(
        db=db,
        title=title,
        body=body,
        event_type="GENERATOR_STOP",
        generator_id=generator.id,
        facility_id=generator.facility_id,
        url="/?tab=tab-dashboard"
    )

    # Check fuel level after stop
    if end_fuel is not None:
        await check_and_notify_low_fuel(db, generator, end_fuel)

    # Check maintenance after stop
    await check_and_notify_maintenance_due(db, generator.id)


async def check_and_notify_low_fuel(
    db: AsyncSession,
    generator: Generator,
    current_fuel_l: float
):
    threshold_l = float(get_runtime_setting("low_fuel_threshold_l", 5.0))
    if current_fuel_l <= threshold_l:
        title = f"⚠️ Критичний рівень палива — {generator.name}"
        body = f"У баку залишилося всього {current_fuel_l:.1f} л (поріг: {threshold_l:.1f} л). Необхідна дозаправка!"
        await send_push_notification(
            db=db,
            title=title,
            body=body,
            event_type="LOW_FUEL",
            generator_id=generator.id,
            facility_id=generator.facility_id,
            url="/?tab=tab-fuel"
        )


async def check_and_notify_maintenance_due(
    db: AsyncSession,
    generator_id: int
):
    """
    Checks if maintenance is due or overdue for generator, and triggers notification
    honoring the maximum 2 notifications per day rule.
    """
    gen_q = select(Generator).where(Generator.id == generator_id)
    gen_res = await db.execute(gen_q)
    generator = gen_res.scalars().first()
    if not generator:
        return

    sched_q = select(MaintenanceSchedule).where(
        MaintenanceSchedule.generator_id == generator_id,
        MaintenanceSchedule.is_active == True
    )
    sched_res = await db.execute(sched_q)
    schedule = sched_res.scalars().first()
    if not schedule:
        return

    remaining_hours = schedule.next_due_hours - generator.current_operating_hours

    if remaining_hours <= 0:
        overdue_h = abs(remaining_hours)
        title = f"🔧 УВАГА: Прострочено ТО — {generator.name}!"
        body = f"Регламент ТО прострочено на {overdue_h:.1f} год (напрацювання: {generator.current_operating_hours:.1f} год, план: {schedule.next_due_hours:.1f} год). Необхідно терміново виконати регламентні роботи!"
        await send_push_notification(
            db=db,
            title=title,
            body=body,
            event_type="MAINTENANCE_DUE",
            generator_id=generator.id,
            facility_id=generator.facility_id,
            url="/?tab=tab-maintenance"
        )
    elif remaining_hours <= (schedule.interval_hours * 0.1):  # within 10% of interval (e.g. <= 30 hours)
        title = f"🔧 Наближається планове ТО — {generator.name}"
        body = f"Залишилося всього {remaining_hours:.1f} мотогодин до регламентного ТО (план: {schedule.next_due_hours:.1f} год). Підготуйте мастило та фільтри."
        await send_push_notification(
            db=db,
            title=title,
            body=body,
            event_type="MAINTENANCE_DUE",
            generator_id=generator.id,
            facility_id=generator.facility_id,
            url="/?tab=tab-maintenance"
        )


async def notify_critical_fault(
    db: AsyncSession,
    generator: Generator,
    fault_title: str,
    fault_description: str
):
    title = f"🚨 Критична несправність — {generator.name}"
    body = f"{fault_title}: {fault_description}"
    await send_push_notification(
        db=db,
        title=title,
        body=body,
        event_type="CRITICAL_FAULT",
        generator_id=generator.id,
        facility_id=generator.facility_id,
        url="/?tab=tab-faults"
    )
