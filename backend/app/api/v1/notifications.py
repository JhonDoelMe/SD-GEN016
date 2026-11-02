import json
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.api.deps import (
    get_current_user,
    get_current_admin,
    require_permission,
    is_user_admin_or_super,
    verify_facility_access,
    verify_generator_facility_access,
    get_client_ip,
)
from backend.app.models.user import User
from backend.app.models.notification import NotificationLog, PushSubscription
from backend.app.schemas.notification import (
    PushSubscriptionIn,
    PushSubscriptionOut,
    NotificationSettingsIn,
    NotificationSettingsOut,
    NotificationLogOut,
    TestNotificationIn,
)
from backend.app.services.notification_service import (
    get_vapid_public_key,
    subscribe_device,
    unsubscribe_device,
    get_notification_settings_data,
    send_push_notification,
    check_and_notify_maintenance_due
)
from backend.app.services.settings_service import update_system_settings
from backend.app.services.audit_service import log_audit

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/vapid-public-key")
async def get_public_vapid_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve VAPID public key for Web Push subscription."""
    pub_key = await get_vapid_public_key(db)
    return {"public_key": pub_key}


@router.post("/subscribe", response_model=PushSubscriptionOut)
async def subscribe_push_notifications(
    sub_in: PushSubscriptionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Register or update current device push subscription for the logged in user."""
    facility_id = verify_facility_access(current_user, sub_in.facility_id or current_user.facility_id)
    sub = await subscribe_device(
        db=db,
        user_id=current_user.id,
        endpoint=sub_in.endpoint,
        p256dh=sub_in.keys.p256dh,
        auth=sub_in.keys.auth,
        user_agent=sub_in.user_agent,
        facility_id=facility_id,
        is_admin=is_user_admin_or_super(current_user)
    )
    return sub


@router.post("/unsubscribe")
async def unsubscribe_push_notifications(
    payload: Dict[str, str],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Unsubscribe current device push endpoint."""
    endpoint = payload.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="Параметр endpoint є обов'язковим")
    ok = await unsubscribe_device(
        db=db,
        endpoint=endpoint,
        user_id=current_user.id,
        is_admin=is_user_admin_or_super(current_user)
    )
    return {"success": ok}


@router.get("/settings", response_model=NotificationSettingsOut)
async def get_notification_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("notifications:view"))
):
    """Get active notification settings and VAPID key."""
    data = await get_notification_settings_data(db)
    return NotificationSettingsOut(**data)


@router.put("/settings", response_model=NotificationSettingsOut)
async def update_notification_settings(
    settings_in: NotificationSettingsIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("notifications:configure"))
):
    """Update notification settings."""

    updates = settings_in.model_dump()
    await update_system_settings(db, updates)

    await log_audit(
        db=db,
        user_id=current_user.id,
        action="NOTIFICATION_SETTINGS_UPDATED",
        entity_type="SystemSetting",
        entity_id="0",
        details={"updated_keys": list(updates.keys())}
    )
    await db.commit()

    data = await get_notification_settings_data(db)
    return NotificationSettingsOut(**data)


@router.post("/test")
async def send_test_notification(
    payload: TestNotificationIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("notifications:configure"))
):
    """Send an immediate test push notification to the current user's own devices."""
    title = payload.title or "🔔 Тестове сповіщення Service Desk"
    body = payload.body or f"Привіт, {current_user.full_name}! Сповіщення успішно налаштовано для вашого облікового запису."

    # Restrict test notifications to ONLY the current user's own subscribed devices (prevents broadcast phishing)
    res = await send_push_notification(
        db=db,
        title=title,
        body=body,
        event_type="TEST",
        facility_id=current_user.facility_id,
        url="/?tab=tab-notifications",
        target_user_id=current_user.id
    )
    return {
        "success": True,
        "message": "Тестове сповіщення відправлено на пристрої",
        **res
    }


@router.get("/logs", response_model=List[NotificationLogOut])
async def get_notification_logs(
    limit: int = Query(30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("notifications:view"))
):
    """Get history of dispatched notifications."""
    q = select(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(limit)
    if not is_user_admin_or_super(current_user) and current_user.facility_id:
        q = q.where(
            (NotificationLog.facility_id == current_user.facility_id)
            | (NotificationLog.facility_id == None)  # noqa: E711
        )
    res = await db.execute(q)
    logs = res.scalars().all()
    return logs


@router.delete("/logs")
async def clear_notification_logs(
    facility_id: Optional[int] = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("notifications:configure"))
):
    """Очищення історії надісланих сповіщень (для адміністратора)."""
    if not is_user_admin_or_super(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Очищення журналу сповіщень дозволено лише Адміністратору"
        )

    stmt = delete(NotificationLog)
    if not current_user.is_superadmin and current_user.facility_id:
        stmt = stmt.where(NotificationLog.facility_id == current_user.facility_id)
    elif facility_id is not None:
        stmt = stmt.where(NotificationLog.facility_id == facility_id)

    res = await db.execute(stmt)
    await db.commit()

    client_ip = get_client_ip(request) if request else None
    await log_audit(
        db=db,
        action="NOTIFICATION_LOGS_CLEARED",
        entity_type="NotificationLog",
        entity_id=None,
        details=f"Користувач {current_user.login} очистив журнал сповіщень. Видалено записів: {res.rowcount}",
        user_id=current_user.id,
        ip_address=client_ip
    )

    return {"success": True, "status": "success", "deleted_count": res.rowcount}


@router.post("/check-maintenance/{generator_id}")
async def check_generator_maintenance_notification(
    generator_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Manually check maintenance schedule and trigger reminder if due (max 2 times per day)."""
    await verify_generator_facility_access(db, current_user, generator_id)
    await check_and_notify_maintenance_due(db, generator_id)
    return {"success": True, "message": "Перевірку регламенту ТО виконано"}
