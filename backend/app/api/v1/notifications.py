import json
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.api.deps import get_current_user, get_current_admin, require_permission
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
    facility_id = sub_in.facility_id or current_user.facility_id
    sub = await subscribe_device(
        db=db,
        user_id=current_user.id,
        endpoint=sub_in.endpoint,
        p256dh=sub_in.keys.p256dh,
        auth=sub_in.keys.auth,
        user_agent=sub_in.user_agent,
        facility_id=facility_id
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
    ok = await unsubscribe_device(db=db, endpoint=endpoint)
    return {"success": ok}


@router.get("/settings", response_model=NotificationSettingsOut)
async def get_notification_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get active notification settings and VAPID key."""
    data = await get_notification_settings_data(db)
    return NotificationSettingsOut(**data)


@router.put("/settings", response_model=NotificationSettingsOut)
async def update_notification_settings(
    settings_in: NotificationSettingsIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update notification settings (Admin or SuperAdmin only)."""
    user_roles_names = [r.name for r in current_user.roles]
    if not current_user.is_superadmin and "Admin" not in user_roles_names:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Тільки адміністратор може змінювати системні налаштування сповіщень"
        )

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
    current_user: User = Depends(get_current_user)
):
    """Send an immediate test push notification to verify sound, vibration and system drawer banner."""
    title = payload.title or "🔔 Тестове сповіщення Service Desk"
    body = payload.body or f"Привіт, {current_user.full_name}! Сповіщення успішно налаштовано для вашого облікового запису."

    res = await send_push_notification(
        db=db,
        title=title,
        body=body,
        event_type="TEST",
        facility_id=current_user.facility_id,
        url="/?tab=tab-notifications"
    )
    return {
        "success": True,
        "message": "Тестове сповіщення відправлено на пристрої",
        **res
    }


@router.get("/logs", response_model=List[NotificationLogOut])
async def get_notification_logs(
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get history of dispatched notifications."""
    q = select(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(limit)
    res = await db.execute(q)
    logs = res.scalars().all()
    return logs


@router.post("/check-maintenance/{generator_id}")
async def check_generator_maintenance_notification(
    generator_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Manually check maintenance schedule and trigger reminder if due (max 2 times per day)."""
    await check_and_notify_maintenance_due(db, generator_id)
    return {"success": True, "message": "Перевірку регламенту ТО виконано"}
