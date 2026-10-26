import datetime
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.audit import AuditLog
from backend.app.schemas.audit import AuditLogOut
from backend.app.api.deps import require_permission, get_current_superadmin
from backend.app.services.audit_service import sanitize_audit_details
from backend.app.services.report_service import generate_audit_excel_report, parse_report_dt

router = APIRouter(prefix="/audit", tags=["Аудит"])


def _safe_details_json(raw_json: Optional[str]) -> Optional[str]:
    if not raw_json:
        return None
    try:
        data = json.loads(raw_json)
        sanitized = sanitize_audit_details(data)
        return json.dumps(sanitized, ensure_ascii=False, default=str)
    except Exception:
        return raw_json


@router.get("", response_model=List[AuditLogOut])
async def list_audit_logs(
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("audit:view"))
):
    q = select(AuditLog).options(selectinload(AuditLog.user)).order_by(AuditLog.id.desc()).limit(limit)
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
            user_name=(log.user.full_name or log.user.login) if log.user else "Система",
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            details_json=_safe_details_json(log.details_json),
            ip_address=log.ip_address,
            created_at=log.created_at
        )
        for log in logs
    ]


@router.get("/export-excel")
async def export_audit_excel(
    facility_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin)
):
    """
    Експорт журналу дій операційного аудиту та системних коригувань в Excel (.xlsx).
    Формує двоаркушеву книгу за стандартом ДСТУ 4163:2020.
    Доступно виключно Головному суперадміністратору.
    """
    start_dt = parse_report_dt(start_date, is_end=False)
    end_dt = parse_report_dt(end_date, is_end=True)

    excel_bytes = await generate_audit_excel_report(
        db=db,
        facility_id=facility_id,
        start_date=start_dt,
        end_date=end_dt,
        action=action,
        entity_type=entity_type
    )

    date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Audit_Report_{date_str}.xlsx"

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
