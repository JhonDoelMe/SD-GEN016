from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.generator import Generator
from backend.app.models.fuel import FuelStock
from backend.app.models.maintenance import MaintenanceSchedule
from backend.app.models.audit import SystemAdjustment
from backend.app.schemas.audit import SystemAdjustmentCreate, SystemAdjustmentOut
from backend.app.api.deps import get_current_superadmin, require_permission, get_client_ip
from backend.app.services.audit_service import record_system_adjustment

router = APIRouter(prefix="/adjustments", tags=["Системні коригування (SuperAdmin)"])


@router.get("", response_model=List[SystemAdjustmentOut])
async def list_adjustments(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("audit:view"))
):
    res = await db.execute(select(SystemAdjustment).order_by(SystemAdjustment.id.desc()).limit(limit))
    items = res.scalars().all()
    return [
        SystemAdjustmentOut(
            id=i.id,
            user_id=i.user_id,
            user_name=i.user.full_name if i.user else None,
            entity_type=i.entity_type,
            entity_id=i.entity_id,
            field_name=i.field_name,
            old_value=i.old_value,
            new_value=i.new_value,
            reason=i.reason,
            created_at=i.created_at
        )
        for i in items
    ]


@router.post("", response_model=SystemAdjustmentOut, status_code=status.HTTP_201_CREATED)
async def perform_adjustment(
    data: SystemAdjustmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    # Strict requirement: only SuperAdmin can perform system adjustments (Section 5)
    current_user: User = Depends(get_current_superadmin)
):
    if len(data.reason.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Обов'язково вкажіть змістовну причину системного коригування"
        )

    old_val_str = ""
    target_entity_type = data.entity_type.strip()

    if target_entity_type == "Generator":
        gen = await db.get(Generator, data.entity_id)
        if not gen:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

        if data.field_name == "current_operating_hours":
            old_val_str = str(gen.current_operating_hours)
            gen.current_operating_hours = float(data.new_value)
        elif data.field_name == "fuel_tank_level_l":
            old_val_str = str(gen.fuel_tank_level_l)
            gen.fuel_tank_level_l = float(data.new_value)
        elif data.field_name == "status":
            old_val_str = str(gen.status)
            gen.status = str(data.new_value)
        elif data.field_name == "nominal_consumption_l_per_h":
            old_val_str = str(gen.nominal_consumption_l_per_h)
            gen.nominal_consumption_l_per_h = float(data.new_value)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Непідтримуване поле: {data.field_name}")

    elif target_entity_type == "FuelStock":
        stock = await db.get(FuelStock, data.entity_id)
        if not stock:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")

        if data.field_name == "current_balance_l":
            old_val_str = str(stock.current_balance_l)
            stock.current_balance_l = float(data.new_value)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Непідтримуване поле: {data.field_name}")

    elif target_entity_type == "MaintenanceSchedule":
        sched = await db.get(MaintenanceSchedule, data.entity_id)
        if not sched:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Графік ТО не знайдено")

        if data.field_name == "interval_hours":
            old_val_str = str(sched.interval_hours)
            sched.interval_hours = float(data.new_value)
        elif data.field_name == "next_due_hours":
            old_val_str = str(sched.next_due_hours)
            sched.next_due_hours = float(data.new_value)
        elif data.field_name == "last_performed_hours":
            old_val_str = str(sched.last_performed_hours)
            sched.last_performed_hours = float(data.new_value)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Непідтримуване поле: {data.field_name}")

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Непідтримувана сутність для системного коригування: {target_entity_type}"
        )

    adj = await record_system_adjustment(
        db=db,
        user_id=current_user.id,
        entity_type=target_entity_type,
        entity_id=data.entity_id,
        field_name=data.field_name,
        old_value=old_val_str,
        new_value=data.new_value,
        reason=data.reason,
        ip_address=get_client_ip(request)
    )
    await db.commit()

    return SystemAdjustmentOut(
        id=adj.id,
        user_id=adj.user_id,
        user_name=current_user.full_name,
        entity_type=adj.entity_type,
        entity_id=adj.entity_id,
        field_name=adj.field_name,
        old_value=adj.old_value,
        new_value=adj.new_value,
        reason=adj.reason,
        created_at=adj.created_at
    )
