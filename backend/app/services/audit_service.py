import json
import datetime
from typing import Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.audit import AuditLog, SystemAdjustment


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


async def log_audit(
    db: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    user_id: Optional[int] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None
) -> AuditLog:
    details_str = json.dumps(details, ensure_ascii=False, default=str) if details else None
    audit = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details_json=details_str,
        ip_address=ip_address,
        created_at=utc_now()
    )
    db.add(audit)
    await db.flush()
    return audit


async def record_system_adjustment(
    db: AsyncSession,
    user_id: int,
    entity_type: str,
    entity_id: int,
    field_name: str,
    old_value: Any,
    new_value: Any,
    reason: str,
    ip_address: Optional[str] = None
) -> SystemAdjustment:
    adj = SystemAdjustment(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        old_value=str(old_value),
        new_value=str(new_value),
        reason=reason.strip(),
        created_at=utc_now()
    )
    db.add(adj)
    await db.flush()

    # Also register this adjustment in the central audit log
    await log_audit(
        db=db,
        action="SYSTEM_ADJUSTMENT",
        entity_type=entity_type,
        entity_id=str(entity_id),
        user_id=user_id,
        details={
            "field": field_name,
            "old_value": str(old_value),
            "new_value": str(new_value),
            "reason": reason.strip(),
        },
        ip_address=ip_address
    )
    return adj
