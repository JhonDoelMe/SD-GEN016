import json
import datetime
from typing import Optional, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.audit import AuditLog, SystemAdjustment

SENSITIVE_KEY_MARKERS = (
    "password", "passwd", "pwd", "secret", "token", "credential", "api_key", "private_key"
)


def is_sensitive_key(key: str) -> bool:
    """Returns True if the key name indicates a sensitive secret."""
    k = str(key).lower()
    return any(marker in k for marker in SENSITIVE_KEY_MARKERS)


def sanitize_audit_details(data: Any) -> Any:
    """
    Recursively inspects dicts and lists, redacting any sensitive fields such as
    passwords, tokens, API keys and secrets with '[REDACTED]'.
    """
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if is_sensitive_key(k):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_audit_details(v)
        return sanitized
    elif isinstance(data, (list, tuple)):
        return [sanitize_audit_details(item) for item in data]
    return data


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
    sanitized = sanitize_audit_details(details) if details else None
    details_str = json.dumps(sanitized, ensure_ascii=False, default=str) if sanitized else None
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
    facility_id: Optional[int] = None,
    target_name: Optional[str] = None,
    ip_address: Optional[str] = None
) -> SystemAdjustment:
    sanitized_old = "[REDACTED]" if is_sensitive_key(field_name) else str(old_value)
    sanitized_new = "[REDACTED]" if is_sensitive_key(field_name) else str(new_value)
    adj = SystemAdjustment(
        user_id=user_id,
        facility_id=facility_id,
        target_name=target_name,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        old_value=sanitized_old,
        new_value=sanitized_new,
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
            "facility_id": facility_id,
            "target_name": target_name,
            "field": field_name,
            "old_value": sanitized_old,
            "new_value": sanitized_new,
            "reason": reason.strip(),
        },
        ip_address=ip_address
    )
    return adj


async def sanitize_historical_audit_logs(db: AsyncSession) -> int:
    """
    Scans existing AuditLog records for any unredacted sensitive keys in details_json,
    sanitizes them, and persists the sanitized JSON. Returns the count of sanitized records.
    """
    res = await db.execute(select(AuditLog))
    logs = res.scalars().all()
    count = 0
    for log in logs:
        if not log.details_json:
            continue
        try:
            parsed = json.loads(log.details_json)
        except Exception:
            continue

        sanitized = sanitize_audit_details(parsed)
        sanitized_str = json.dumps(sanitized, ensure_ascii=False, default=str)
        if sanitized_str != log.details_json:
            log.details_json = sanitized_str
            count += 1
    if count > 0:
        await db.commit()
    return count

