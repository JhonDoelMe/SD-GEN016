from typing import List, Optional
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.fault import Fault
from backend.app.schemas.fault import FaultCreate, FaultStatusUpdate, FaultOut
from backend.app.api.deps import get_current_user, require_permission, get_client_ip
from backend.app.services.fault_service import create_fault, update_fault_status

router = APIRouter(prefix="/faults", tags=["Несправності"])


@router.get("", response_model=List[FaultOut])
async def list_faults(
    status_filter: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = select(Fault).order_by(Fault.id.desc()).limit(limit)
    if status_filter:
        q = q.where(Fault.status == status_filter)
    res = await db.execute(q)
    faults = res.scalars().all()
    return [
        FaultOut(
            id=f.id,
            generator_id=f.generator_id,
            user_id=f.user_id,
            user_name=f.user.full_name if f.user else None,
            title=f.title,
            description=f.description,
            operating_hours=f.operating_hours,
            priority=f.priority,
            status=f.status,
            photo_urls=f.photo_urls,
            resolved_by_id=f.resolved_by_id,
            resolved_by_name=f.resolved_by.full_name if f.resolved_by else None,
            resolution_notes=f.resolution_notes,
            resolved_at=f.resolved_at,
            created_at=f.created_at,
            updated_at=f.updated_at
        )
        for f in faults
    ]


@router.post("", response_model=FaultOut, status_code=status.HTTP_201_CREATED)
async def report_fault(
    data: FaultCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("faults:create"))
):
    fault = await create_fault(
        db=db,
        fault_data=data,
        user_id=current_user.id,
        ip_address=get_client_ip(request)
    )
    return FaultOut(
        id=fault.id,
        generator_id=fault.generator_id,
        user_id=fault.user_id,
        user_name=current_user.full_name,
        title=fault.title,
        description=fault.description,
        operating_hours=fault.operating_hours,
        priority=fault.priority,
        status=fault.status,
        photo_urls=fault.photo_urls,
        resolved_by_id=fault.resolved_by_id,
        resolved_by_name=None,
        resolution_notes=fault.resolution_notes,
        resolved_at=fault.resolved_at,
        created_at=fault.created_at,
        updated_at=fault.updated_at
    )


@router.put("/{fault_id}/status", response_model=FaultOut)
async def change_fault_status(
    fault_id: int,
    data: FaultStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("faults:manage"))
):
    fault = await update_fault_status(
        db=db,
        fault_id=fault_id,
        status_data=data,
        user_id=current_user.id,
        ip_address=get_client_ip(request)
    )
    return FaultOut(
        id=fault.id,
        generator_id=fault.generator_id,
        user_id=fault.user_id,
        user_name=fault.user.full_name if fault.user else None,
        title=fault.title,
        description=fault.description,
        operating_hours=fault.operating_hours,
        priority=fault.priority,
        status=fault.status,
        photo_urls=fault.photo_urls,
        resolved_by_id=fault.resolved_by_id,
        resolved_by_name=fault.resolved_by.full_name if fault.resolved_by else None,
        resolution_notes=fault.resolution_notes,
        resolved_at=fault.resolved_at,
        created_at=fault.created_at,
        updated_at=fault.updated_at
    )
