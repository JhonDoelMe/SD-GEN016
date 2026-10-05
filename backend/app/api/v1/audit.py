from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.audit import AuditLog
from backend.app.schemas.audit import AuditLogOut
from backend.app.api.deps import require_permission

router = APIRouter(prefix="/audit", tags=["Аудит"])


@router.get("", response_model=List[AuditLogOut])
async def list_audit_logs(
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("audit:view"))
):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)

    res = await db.execute(q)
    logs = res.scalars().all()
    return [
        AuditLogOut(
            id=log.id,
            user_id=log.user_id,
            user_name=log.user.full_name if log.user else "Система",
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            details_json=log.details_json,
            ip_address=log.ip_address,
            created_at=log.created_at
        )
        for log in logs
    ]
