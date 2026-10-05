from typing import List, Optional
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.maintenance import MaintenanceRecord
from backend.app.schemas.maintenance import (
    MaintenanceScheduleOut, MaintenanceRecordCreate, MaintenanceRecordOut
)
from backend.app.api.deps import get_current_user, require_permission, get_client_ip
from backend.app.services.maintenance_service import (
    get_maintenance_schedule_status, record_maintenance
)

router = APIRouter(prefix="/maintenance", tags=["Технічне обслуговування"])


@router.get("/schedule", response_model=MaintenanceScheduleOut)
async def get_schedule(
    generator_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await get_maintenance_schedule_status(db, generator_id)


@router.post("/record", response_model=MaintenanceRecordOut, status_code=status.HTTP_201_CREATED)
async def create_maintenance_record(
    data: MaintenanceRecordCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Check permissions based on type
    if data.maintenance_type == "SCHEDULED":
        checker = require_permission("maintenance:perform_scheduled")
        await checker(current_user)
    else:
        checker = require_permission("maintenance:create_intermediate")
        await checker(current_user)

    record = await record_maintenance(
        db=db,
        data=data,
        user_id=current_user.id,
        ip_address=get_client_ip(request)
    )

    return MaintenanceRecordOut(
        id=record.id,
        generator_id=record.generator_id,
        user_id=record.user_id,
        user_name=current_user.full_name,
        maintenance_type=record.maintenance_type,
        operating_hours=record.operating_hours,
        work_description=record.work_description,
        consumables_used=record.consumables_used,
        cost=record.cost,
        comment=record.comment,
        photo_urls=record.photo_urls,
        created_at=record.created_at
    )


@router.get("/records", response_model=List[MaintenanceRecordOut])
async def list_maintenance_records(
    generator_id: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = select(MaintenanceRecord).order_by(MaintenanceRecord.id.desc()).limit(limit)
    if generator_id:
        q = q.where(MaintenanceRecord.generator_id == generator_id)
    res = await db.execute(q)
    records = res.scalars().all()
    return [
        MaintenanceRecordOut(
            id=r.id,
            generator_id=r.generator_id,
            user_id=r.user_id,
            user_name=r.user.full_name if r.user else None,
            maintenance_type=r.maintenance_type,
            operating_hours=r.operating_hours,
            work_description=r.work_description,
            consumables_used=r.consumables_used,
            cost=r.cost,
            comment=r.comment,
            photo_urls=r.photo_urls,
            created_at=r.created_at
        )
        for r in records
    ]
