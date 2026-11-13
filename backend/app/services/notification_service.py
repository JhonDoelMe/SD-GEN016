import json
import base64
import logging
import datetime
import asyncio
from typing import Dict, Any, Optional, Tuple, List
from fastapi import HTTPException, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from py_vapid import Vapid
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import pywebpush

from backend.app.models.settings import SystemSetting
from backend.app.models.notification import PushSubscription, NotificationLog
from backend.app.models.generator import Generator
from backend.app.models.facility import Facility
from backend.app.models.maintenance import MaintenanceSchedule
from backend.app.services.settings_service import get_runtime_setting, set_runtime_setting
from backend.app.services.fcm_service import send_fcm_message
from backend.app.core.timezone import now_utc, now_facility, get_facility_tz

logger = logging.getLogger(__name__)


def _clean_sub_claim(raw_val: Any) -> str:
    """Normalize and validate VAPID claims 'sub' into a strict RFC-compliant mailto: URI."""
    default_sub = "mailto:maxiuallc@gmail.com"
    if not raw_val:
        return default_sub
    val = raw_val
    try:
        val = json.loads(val)
    except Exception:
        pass
    val = str(val).strip().strip('"\'').strip()
    if not val:
        return default_sub
    if not val.startswith("mailto:") and not val.startswith("https://"):
        if "@" in val:
            val = f"mailto:{val}"
        else:
            return default_sub
    return val


async def get_or_create_vapid_keys(db: AsyncSession) -> Tuple[str, str, str]:
    """
    Retrieve existing VAPID keys from system_settings or generate and persist new ones.
    NOTIF-01: Перевіряє цілісність пари ключів та валідність приватного ключа.
    При відновленні неповної або пошкодженої пари оновлення виконується атомарно без конфліктів primary key.
    """
    q = select(SystemSetting).where(SystemSetting.key.in_(["vapid_public_key", "vapid_private_key_pem", "vapid_claims_sub"]))
    res = await db.execute(q)
    rows_map = {r.key: r for r in res.scalars().all()}

    pub_row = rows_map.get("vapid_public_key")
    priv_row = rows_map.get("vapid_private_key_pem")
    sub_row = rows_map.get("vapid_claims_sub")

    sub_claim = _clean_sub_claim(sub_row.value_json if sub_row else None)

    if pub_row and priv_row:
        try:
            pub_clean = json.loads(pub_row.value_json)
        except Exception:
            pub_clean = pub_row.value_json
        try:
            priv_clean = json.loads(priv_row.value_json)
        except Exception:
            priv_clean = priv_row.value_json

        # NOTIF-01: Перевіряємо валідність приватного ключа
        try:
            Vapid.from_pem(priv_clean.encode("utf-8"))
            return pub_clean, priv_clean, sub_claim
        except Exception as ex:
            logger.warning("NOTIF-01: Пошкоджений VAPID приватний ключ (%s). Виконується контрольоване перестворення пари ключів.", ex)

    # Generate new VAPID EC P-256 keys
    vapid = Vapid()
    vapid.generate_keys()
    raw_pub = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    new_pub_b64 = base64.urlsafe_b64encode(raw_pub).decode("ascii").rstrip("=")
    new_priv_pem = vapid.private_pem().decode("utf-8")

    # Persist / Upsert in database atomically
    if pub_row:
        pub_row.value_json = json.dumps(new_pub_b64)
    else:
        db.add(SystemSetting(key="vapid_public_key", value_json=json.dumps(new_pub_b64), description="VAPID Web Push Public Key (base64url)"))

    if priv_row:
        priv_row.value_json = json.dumps(new_priv_pem)
    else:
        db.add(SystemSetting(key="vapid_private_key_pem", value_json=json.dumps(new_priv_pem), description="VAPID Web Push Private Key (PEM)"))

    if not sub_row:
        db.add(SystemSetting(key="vapid_claims_sub", value_json=json.dumps(sub_claim), description="VAPID Web Push Subject Claim"))

    await db.commit()
    logger.info("NOTIF-01: Успішно збережено нову пару VAPID ключів.")
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
    facility_id: Optional[int] = None,
    is_admin: bool = False
) -> PushSubscription:
    q = select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    res = await db.execute(q)
    sub = res.scalars().first()

    now = now_utc(naive=True)
    if sub:
        # NOTIF-02: Захист власності підписки. Звичайний користувач може оновлювати лише власну підписку.
        # Збіг криптографічних ключів не є підставою для зміни власника.
        if sub.user_id != user_id and not is_admin:
            logger.warning(
                "NOTIF-02: Спроба перепризначення підписки ID %s користувача %s на користувача %s без прав адміністратора",
                sub.id, sub.user_id, user_id
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ця підписка вже зареєстрована за іншим користувачем. Зміна власника заборонена."
            )
        if is_admin and sub.user_id != user_id:
            logger.info(
                "NOTIF-02: Адміністративне перепризначення підписки ID %s з користувача %s на користувача %s",
                sub.id, sub.user_id, user_id
            )
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


async def unsubscribe_device(
    db: AsyncSession,
    endpoint: str,
    user_id: Optional[int] = None,
    is_admin: bool = False
) -> bool:
    q = select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    res = await db.execute(q)
    sub = res.scalars().first()
    if sub:
        # NOTIF-03: Безпечне скасування підписки.
        # Для не-адміністратора обов'язково перевіряється відповідність user_id.
        if not is_admin:
            if user_id is None or sub.user_id != user_id:
                logger.warning(
                    "NOTIF-03: Відхилено спробу деактивації підписки ID %s користувача %s неавторизованим запитом (user_id=%s)",
                    sub.id, sub.user_id, user_id
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Ви можете відписати лише власний пристрій"
                )
        sub.is_active = False
        sub.updated_at = now_utc(naive=True)
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
        "notify_yasno_outages": bool(get_runtime_setting("notify_yasno_outages", True)),
        "notify_air_alerts": bool(get_runtime_setting("notify_air_alerts", True)),
        "notify_air_alert_end": bool(get_runtime_setting("notify_air_alert_end", True)),
        "vapid_public_key": pub_key,
        "active_subscriptions_count": active_count
    }


def _send_single_webpush_sync(sub_info: Dict[str, Any], payload_str: str, vapid_obj: Any, claims: Dict[str, str]) -> Tuple[bool, bool]:
    """
    Synchronous WebPush sender executed in threadpool.
    NOTIF-08 / NOTIF-09: Безпечне логування через logger без витоку секретів,
    деактивація підписки виключно при підтверджених HTTP 404/410.
    Returns: (success: bool, is_expired: bool)
    """
    endpoint = sub_info.get("endpoint", "")
    masked_ep = (endpoint[:35] + "...") if len(endpoint) > 35 else endpoint
    try:
        # Use copy of claims to avoid cross-request mutation of 'aud' by pywebpush
        claims_copy = dict(claims) if claims else {}
        vapid_key = vapid_obj
        if isinstance(vapid_key, str) and "BEGIN" in vapid_key:
            vapid_key = Vapid.from_pem(vapid_key.encode("utf-8"))
        pywebpush.webpush(
            subscription_info=sub_info,
            data=payload_str,
            vapid_private_key=vapid_key,
            vapid_claims=claims_copy,
            ttl=14400,
            timeout=8.0,
            headers={"Urgency": "high"}
        )
        return True, False
    except pywebpush.WebPushException as ex:
        status_code = getattr(getattr(ex, "response", None), "status_code", None)
        logger.warning("NOTIF-08: WebPushException для endpoint %s (status=%s): %s", masked_ep, status_code, ex)
        # Only 404 or 410 mean the subscription is definitively expired or unsubscribed
        if status_code in (404, 410):
            return False, True
        return False, False
    except Exception as ex:
        logger.error("NOTIF-08: Непередбачена помилка відправки Web Push для %s: %s", masked_ep, ex)
        return False, False


async def send_push_notification(
    db: AsyncSession,
    title: str,
    body: str,
    event_type: str,
    generator_id: Optional[int] = None,
    facility_id: Optional[int] = None,
    url: str = "/",
    target_user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Dispatches a push notification to subscribed devices with anti-spam guards,
    strict rate limiting (e.g. maintenance <= 2 per day), and persistent logging.
    If `target_user_id` is provided (e.g. for TEST notifications), sends ONLY to that user's own devices.
    """
    # 1. Check global notifications enabled
    if not get_runtime_setting("notifications_enabled", True):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "Сповіщення вимкнено в налаштуваннях"}

    # 2. Check event-specific toggles
    event_toggle_map = {
        "GENERATOR_START": "notify_generator_start",
        "GENERATOR_STOP": "notify_generator_stop",
        "GENERATOR_SAFETY_STOP": "notify_generator_stop",
        "GENERATOR_AUTO_STOP": "notify_generator_stop",
        "GENERATOR_HEARTBEAT": "notify_running_heartbeat",
        "OUTSIDE_WORK_HOURS": "notify_outside_schedule",
        "EMPTY_TANK": "notify_low_fuel",
        "LOW_FUEL": "notify_low_fuel",
        "MAINTENANCE_DUE": "notify_maintenance",
        "CRITICAL_FAULT": "notify_critical_faults",
        "YASNO_OUTAGE_ALERT": "notify_yasno_outages",
        "AIR_ALERT_START": "notify_air_alerts",
        "AIR_ALERT_END": "notify_air_alert_end",
    }
    toggle_key = event_toggle_map.get(event_type)
    if toggle_key and not get_runtime_setting(toggle_key, True):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": f"Тип сповіщення {event_type} вимкнено"}
    if event_type == "AIR_ALERT_END" and not get_runtime_setting("notify_air_alerts", True):
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "Сповіщення про повітряні тривоги вимкнено"}

    now = now_utc(naive=True)

    # 3. Rate limiting for MAINTENANCE_DUE (strictly <= max_maintenance_notifications_per_day, default 2)
    if event_type == "MAINTENANCE_DUE" and generator_id:
        max_daily = max(1, int(get_runtime_setting("max_maintenance_notifications_per_day", 2)))

        # NOTIF-05: Визначаємо календарний початок доби згідно з локальним часовим поясом об'єкта
        target_tz_str = None
        if facility_id:
            fac = await db.get(Facility, facility_id)
            if fac and fac.timezone:
                target_tz_str = fac.timezone
        elif generator_id:
            gen = await db.get(Generator, generator_id)
            if gen and gen.facility_id:
                fac = await db.get(Facility, gen.facility_id)
                if fac and fac.timezone:
                    target_tz_str = fac.timezone

        fac_now = now_facility(target_tz_str)
        today_start_fac = fac_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_fac.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        # Отримуємо всі сповіщення ТО за сьогодні для даного генератора
        q_today = select(NotificationLog).where(
            and_(
                NotificationLog.event_type == "MAINTENANCE_DUE",
                NotificationLog.generator_id == generator_id,
                NotificationLog.created_at >= today_start_utc
            )
        ).order_by(NotificationLog.created_at.desc())
        res_today = await db.execute(q_today)
        logs_today = res_today.scalars().all()
        today_count = len(logs_today)

        is_overdue_alert = "прострочено" in title.lower()

        # Ескалація пріоритету: якщо надходить критичне сповіщення про прострочене ТО,
        # воно не блокується попереднім попередженням про наближення ТО
        if today_count >= max_daily:
            if is_overdue_alert:
                has_overdue_today = any("прострочено" in (l.title or "").lower() for l in logs_today)
                if has_overdue_today:
                    return {
                        "sent": 0, "failed": 0, "skipped": True, "rate_limited": True,
                        "reason": f"Денний ліміт нагадувань про ТО ({max_daily} на добу) для цього генератора вже досягнуто"
                    }
            else:
                return {
                    "sent": 0, "failed": 0, "skipped": True, "rate_limited": True,
                    "reason": f"Денний ліміт нагадувань про ТО ({max_daily} на добу) для цього генератора вже досягнуто"
                }

        # Також вимагається інтервал не менше 3 годин між однотипними нагадуваннями
        if logs_today:
            last_time = logs_today[0].created_at
            if (now - last_time).total_seconds() < 10800:  # 3 hours
                if not (is_overdue_alert and "прострочено" not in (logs_today[0].title or "").lower()):
                    return {
                        "sent": 0, "failed": 0, "skipped": True, "rate_limited": True,
                        "reason": "Нагадування про ТО було надіслано менше 3 годин тому"
                    }

    # 4. Rate limiting for LOW_FUEL / EMPTY_TANK / OUTSIDE_WORK_HOURS (cooldown: 3 hours per event type)
    if event_type in ("LOW_FUEL", "EMPTY_TANK", "OUTSIDE_WORK_HOURS") and generator_id:
        q_last_ev = select(NotificationLog.created_at).where(
            and_(
                NotificationLog.event_type == event_type,
                NotificationLog.generator_id == generator_id
            )
        ).order_by(NotificationLog.created_at.desc()).limit(1)
        res_ev = await db.execute(q_last_ev)
        last_ev_time = res_ev.scalar()
        if last_ev_time and (now - last_ev_time).total_seconds() < 10800:  # 3 hours
            return {
                "sent": 0,
                "failed": 0,
                "skipped": True,
                "rate_limited": True,
                "reason": f"Сповіщення {event_type} вже надсилалося менше 3 годин тому"
            }

    # 5. Fetch active subscriptions (with User eagerly loaded)
    sub_query = select(PushSubscription).options(selectinload(PushSubscription.user)).where(PushSubscription.is_active == True)
    if target_user_id is not None:
        sub_query = sub_query.where(PushSubscription.user_id == target_user_id)
    sub_res = await db.execute(sub_query)
    all_active = sub_res.scalars().all()

    # Routing rules:
    # - If target_user_id is set (e.g. test notification), send ONLY to that user's own active devices!
    # - Otherwise, Admins and SuperAdmins ALWAYS receive start, stop, critical fault, low fuel and maintenance notifications!
    # - Other roles (e.g. operators) receive notifications matching their facility or global.
    subscriptions = []
    seen_endpoints = set()
    for s in all_active:
        if s.endpoint in seen_endpoints:
            continue
        user = s.user
        if not user or not user.is_active:
            continue

        if target_user_id is not None:
            if s.user_id == target_user_id:
                subscriptions.append(s)
                seen_endpoints.add(s.endpoint)
            continue

        is_admin_or_super = user.is_superadmin or any(r.name.lower() in ("admin", "superadmin") for r in (user.roles or []))
        if is_admin_or_super:
            subscriptions.append(s)
            seen_endpoints.add(s.endpoint)
        elif not facility_id or user.facility_id is None or s.facility_id is None or s.facility_id == facility_id or user.facility_id == facility_id:
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

    # 6. Prepare VAPID keys, pre-flush log entry for unique tag deduplication, and build payload
    pub_b64, priv_pem, sub_claim = await get_or_create_vapid_keys(db)
    claims = {"sub": _clean_sub_claim(sub_claim)}

    try:
        vapid_obj = Vapid.from_pem(priv_pem.encode("utf-8"))
    except Exception:
        vapid_obj = Vapid.from_string(priv_pem)

    log_entry = NotificationLog(
        event_type=event_type,
        generator_id=generator_id,
        facility_id=facility_id,
        title=title,
        body=body,
        recipients_count=len(subscriptions),
        success_count=0,
        failure_count=0,
        created_at=now
    )
    db.add(log_entry)
    await db.flush()

    payload = json.dumps({
        "title": title,
        "body": body,
        "icon": "/frontend/icons/icon-192.png",
        "badge": "/frontend/icons/icon-192.png",
        "data": {
            "url": url,
            "event_type": event_type,
            "log_id": log_entry.id,
            "facility_id": facility_id,
            "generator_id": generator_id,
        },
        "tag": f"sd-log-{log_entry.id}" if log_entry.id else f"sd-{event_type.lower()}"
    })

    success_count = 0
    failure_count = 0
    expired_sub_ids = []

    push_tasks = []
    fcm_data = {
        "url": url,
        "event_type": event_type,
        "log_id": str(log_entry.id) if log_entry.id else "",
        "facility_id": str(facility_id) if facility_id is not None else "",
        "generator_id": str(generator_id) if generator_id is not None else "",
    }
    for s in subscriptions:
        if s.endpoint and s.endpoint.startswith("fcm://"):
            device_token = s.endpoint[len("fcm://"):]
            push_tasks.append(
                send_fcm_message(
                    device_token=device_token,
                    title=title,
                    body=body,
                    event_type=event_type,
                    data=fcm_data,
                )
            )
            continue

        sub_info = {
            "endpoint": s.endpoint,
            "keys": {
                "p256dh": s.p256dh,
                "auth": s.auth
            }
        }
        push_tasks.append(asyncio.to_thread(_send_single_webpush_sync, sub_info, payload, vapid_obj, claims))

    results = await asyncio.gather(*push_tasks, return_exceptions=True)
    for s, res in zip(subscriptions, results):
        if isinstance(res, Exception):
            failure_count += 1
            continue
        ok, is_expired = res
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

    # 7. Finalize notification log counts
    log_entry.success_count = success_count
    log_entry.failure_count = failure_count
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
    end_fuel: Optional[float],
    suppress_low_fuel: bool = False,
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

    # Check fuel level after stop (suppressed during FuelMeasurement MEASURING phase)
    if not suppress_low_fuel and end_fuel is not None:
        await check_and_notify_low_fuel(db, generator, end_fuel)

    # Check maintenance after stop
    await check_and_notify_maintenance_due(db, generator.id)


async def check_and_notify_low_fuel(
    db: AsyncSession,
    generator: Generator,
    current_fuel_l: float
):
    threshold_l = float(get_runtime_setting("low_fuel_threshold_l", 5.0))
    if current_fuel_l <= 0.1:
        safe_l = max(0.0, float(current_fuel_l))
        title = f"⛽ ПОРОЖНІЙ БАК (0 л) — {generator.name}"
        body = f"У баку генератора закінчилося паливо ({safe_l:.1f} л)! Робота насухо небезпечна — потрібна негайна дозаправка."
        push_res = await send_push_notification(
            db=db,
            title=title,
            body=body,
            event_type="EMPTY_TANK",
            generator_id=generator.id,
            facility_id=generator.facility_id,
            url="/?tab=tab-fuel"
        )
        if not push_res.get("rate_limited") and get_runtime_setting("email_notify_empty_tank", True) and get_runtime_setting("smtp_enabled", False):
            try:
                from backend.app.services.email_service import resolve_facility_email_recipients, send_empty_tank_email
                recs = await resolve_facility_email_recipients(db, generator.facility_id)
                if recs:
                    await send_empty_tank_email(
                        recipients=recs,
                        generator_name=generator.name,
                        fuel_level_l=safe_l,
                        db=db,
                    )
            except Exception as mail_exc:
                logger.warning("Failed to dispatch EMPTY_TANK email: %s", mail_exc)
    elif current_fuel_l <= threshold_l:
        title = f"⚠️ Критичний рівень палива — {generator.name}"
        body = f"У баку залишилося всього {current_fuel_l:.1f} л (поріг: {threshold_l:.1f} л). Необхідна дозаправка!"
        push_res = await send_push_notification(
            db=db,
            title=title,
            body=body,
            event_type="LOW_FUEL",
            generator_id=generator.id,
            facility_id=generator.facility_id,
            url="/?tab=tab-fuel"
        )
        if not push_res.get("rate_limited") and get_runtime_setting("email_notify_low_fuel", True) and get_runtime_setting("smtp_enabled", False):
            try:
                from backend.app.services.email_service import resolve_facility_email_recipients, send_low_fuel_email
                recs = await resolve_facility_email_recipients(db, generator.facility_id)
                if recs:
                    await send_low_fuel_email(
                        recipients=recs,
                        generator_name=generator.name,
                        fuel_level_l=current_fuel_l,
                        threshold_l=threshold_l,
                        db=db,
                    )
            except Exception as mail_exc:
                logger.warning("Failed to dispatch LOW_FUEL email: %s", mail_exc)


async def check_and_notify_maintenance_due(
    db: AsyncSession,
    generator_id: int,
    current_hours: Optional[float] = None
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

    effective_hours = float(current_hours) if current_hours is not None else float(generator.current_operating_hours or 0.0)
    remaining_hours = schedule.next_due_hours - effective_hours

    if remaining_hours <= 0:
        overdue_h = abs(remaining_hours)
        title = f"🔧 УВАГА: Прострочено ТО — {generator.name}!"
        body = f"Регламент ТО прострочено на {overdue_h:.1f} год (напрацювання: {effective_hours:.1f} год, план: {schedule.next_due_hours:.1f} год). Необхідно терміново виконати регламентні роботи!"
        push_res = await send_push_notification(
            db=db,
            title=title,
            body=body,
            event_type="MAINTENANCE_DUE",
            generator_id=generator.id,
            facility_id=generator.facility_id,
            url="/?tab=tab-maintenance"
        )
        if not push_res.get("rate_limited") and get_runtime_setting("email_notify_maintenance_due", True) and get_runtime_setting("smtp_enabled", False):
            try:
                from backend.app.services.email_service import resolve_facility_email_recipients, send_maintenance_due_email
                recs = await resolve_facility_email_recipients(db, generator.facility_id)
                if recs:
                    await send_maintenance_due_email(
                        recipients=recs,
                        generator_name=generator.name,
                        is_overdue=True,
                        hours_delta=overdue_h,
                        effective_hours=effective_hours,
                        next_due_hours=schedule.next_due_hours,
                        db=db,
                    )
            except Exception as mail_exc:
                logger.warning("Failed to dispatch MAINTENANCE_DUE overdue email: %s", mail_exc)
    elif remaining_hours <= (schedule.interval_hours * 0.1):  # within 10% of interval (e.g. <= 30 hours)
        title = f"🔧 Наближається планове ТО — {generator.name}"
        body = f"Залишилося всього {remaining_hours:.1f} мотогодин до регламентного ТО (план: {schedule.next_due_hours:.1f} год). Підготуйте мастило та фільтри."
        push_res = await send_push_notification(
            db=db,
            title=title,
            body=body,
            event_type="MAINTENANCE_DUE",
            generator_id=generator.id,
            facility_id=generator.facility_id,
            url="/?tab=tab-maintenance"
        )
        if not push_res.get("rate_limited") and get_runtime_setting("email_notify_maintenance_due", True) and get_runtime_setting("smtp_enabled", False):
            try:
                from backend.app.services.email_service import resolve_facility_email_recipients, send_maintenance_due_email
                recs = await resolve_facility_email_recipients(db, generator.facility_id)
                if recs:
                    await send_maintenance_due_email(
                        recipients=recs,
                        generator_name=generator.name,
                        is_overdue=False,
                        hours_delta=remaining_hours,
                        effective_hours=effective_hours,
                        next_due_hours=schedule.next_due_hours,
                        db=db,
                    )
            except Exception as mail_exc:
                logger.warning("Failed to dispatch MAINTENANCE_DUE upcoming email: %s", mail_exc)


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
    if get_runtime_setting("email_notify_critical_fault", True) and get_runtime_setting("smtp_enabled", False):
        try:
            from backend.app.services.email_service import resolve_facility_email_recipients, send_critical_fault_email
            recs = await resolve_facility_email_recipients(db, generator.facility_id)
            if recs:
                await send_critical_fault_email(
                    recipients=recs,
                    generator_name=generator.name,
                    fault_title=fault_title,
                    fault_description=fault_description,
                    db=db,
                )
        except Exception as mail_exc:
            logger.warning("Failed to dispatch CRITICAL_FAULT email: %s", mail_exc)


async def notify_outside_work_hours(
    db: AsyncSession,
    generator: Generator,
    schedule_msg: str,
    context_text: str,
):
    title = f"🕒 Робота поза графіком — {generator.name}"
    body = f"{context_text} ({schedule_msg})"
    push_res = await send_push_notification(
        db=db,
        title=title,
        body=body,
        event_type="OUTSIDE_WORK_HOURS",
        generator_id=generator.id,
        facility_id=generator.facility_id,
        url="/?tab=tab-dashboard"
    )
    if not push_res.get("rate_limited") and get_runtime_setting("email_notify_outside_schedule", True) and get_runtime_setting("smtp_enabled", False):
        try:
            from backend.app.services.email_service import resolve_facility_email_recipients, send_outside_work_hours_email
            recs = await resolve_facility_email_recipients(db, generator.facility_id)
            if recs:
                await send_outside_work_hours_email(
                    recipients=recs,
                    generator_name=generator.name,
                    schedule_msg=schedule_msg,
                    context_text=context_text,
                    db=db,
                )
        except Exception as mail_exc:
            logger.warning("Failed to dispatch OUTSIDE_WORK_HOURS email: %s", mail_exc)


async def notify_air_alert_start(
    db: AsyncSession,
    facility_id: int,
    facility_name: str,
    city_name: str,
    level: str,
    threat_title: str,
    threat_icon: str = "🚨",
    location_title: str = "",
    operator_advice: str = "",
    running_generator_names: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Sends push notification when an air alert (or drone/ballistic threat) starts or escalates at a facility.
    """
    loc_label = city_name or location_title or "регіон"
    if level == "yellow":
        title = f"🛸 Підвищена загроза — {facility_name} ({loc_label})"
    else:
        title = f"🚨 Повітряна тривога — {facility_name} ({loc_label})"

    parts = [f"{threat_icon} {threat_title}."]
    if running_generator_names:
        gens_str = ", ".join(running_generator_names)
        parts.append(
            f"⚡ Генератор ({gens_str}) зараз у роботі — НЕ виходьте до генератора та НЕ проводьте заправку палива на відкритому просторі до відбою!"
        )
    elif operator_advice:
        parts.append(operator_advice)
    else:
        parts.append("Дотримуйтесь правил безпеки та перебувайте в укритті.")

    return await send_push_notification(
        db=db,
        title=title,
        body=" ".join(parts),
        event_type="AIR_ALERT_START",
        facility_id=facility_id,
        url="/?tab=tab-dashboard"
    )


async def notify_air_alert_end(
    db: AsyncSession,
    facility_id: int,
    facility_name: str,
    city_name: str,
    duration_minutes: int = 0
) -> Dict[str, Any]:
    """
    Sends push notification when an air alert ends (All-Clear / Відбій тривоги) at a facility.
    """
    loc_label = city_name or "регіон"
    title = f"🟢 Відбій повітряної тривоги — {facility_name} ({loc_label})"
    dur_str = ""
    if duration_minutes and duration_minutes > 0:
        if duration_minutes >= 60:
            h = duration_minutes // 60
            m = duration_minutes % 60
            dur_str = f" (тривала {h} год {m} хв)" if m else f" (тривала {h} год)"
        else:
            dur_str = f" (тривала {duration_minutes} хв)"

    body = f"Небо чисте{dur_str}. Загрозу скасовано — дозволено штатний огляд, заправку палива та обслуговування генераторів."
    return await send_push_notification(
        db=db,
        title=title,
        body=body,
        event_type="AIR_ALERT_END",
        facility_id=facility_id,
        url="/?tab=tab-dashboard"
    )
