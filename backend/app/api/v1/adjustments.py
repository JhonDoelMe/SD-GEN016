import math
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.facility import Facility
from backend.app.models.generator import Generator
from backend.app.models.fuel import FuelStock
from backend.app.models.maintenance import MaintenanceSchedule
from backend.app.models.audit import SystemAdjustment
from backend.app.schemas.audit import SystemAdjustmentCreate, SystemAdjustmentOut
from backend.app.api.deps import get_current_superadmin, require_permission, get_client_ip
from backend.app.services.audit_service import record_system_adjustment

router = APIRouter(prefix="/adjustments", tags=["Системні коригування (SuperAdmin)"])

ALLOWED_GENERATOR_STATUSES = {"STOPPED", "RUNNING", "MAINTENANCE_REQUIRED", "FAULTY", "BLOCKED"}


def _parse_float(raw: str, field_name: str) -> float:
    try:
        val = float(str(raw).replace(",", ".").strip())
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Некоректне числове значення для поля '{field_name}'"
        )
    if not math.isfinite(val):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Значення поля '{field_name}' повинно бути скінченним числом"
        )
    return round(val, 3)


def _parse_non_negative_float(raw: str, field_name: str) -> float:
    try:
        val = float(raw)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Некоректне числове значення для поля '{field_name}'"
        )
    if not math.isfinite(val) or val < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Значення поля '{field_name}' повинно бути скінченним невід'ємним числом"
        )
    return val


@router.get("", response_model=List[SystemAdjustmentOut])
async def list_adjustments(
    limit: int = Query(50, ge=1, le=500),
    facility_id: Optional[int] = Query(None, description="Фільтр за об'єктом"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("audit:view"))
):
    query = (
        select(SystemAdjustment)
        .options(selectinload(SystemAdjustment.user), selectinload(SystemAdjustment.facility))
    )
    if facility_id:
        query = query.where(SystemAdjustment.facility_id == facility_id)

    query = query.order_by(SystemAdjustment.id.desc()).limit(limit)
    res = await db.execute(query)
    items = res.scalars().all()
    return [
        SystemAdjustmentOut(
            id=i.id,
            user_id=i.user_id,
            user_name=i.user.full_name if i.user else None,
            facility_id=i.facility_id,
            facility_name=i.facility.name if i.facility else None,
            target_name=i.target_name,
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
    target_facility_id = data.facility_id
    target_name = None

    if target_entity_type == "Generator":
        gen = await db.get(Generator, data.entity_id)
        if not gen:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")
        target_facility_id = gen.facility_id or target_facility_id
        target_name = f"{gen.name} ({gen.model or 'Генератор'})"

        if data.field_name == "current_operating_hours":
            old_val_str = str(gen.current_operating_hours)
            gen.current_operating_hours = _parse_non_negative_float(data.new_value, data.field_name)
        elif data.field_name == "fuel_tank_level_l":
            old_val_str = str(gen.fuel_tank_level_l)
            gen.fuel_tank_level_l = _parse_float(data.new_value, data.field_name)
        elif data.field_name == "status":
            new_status = str(data.new_value).strip().upper()
            if new_status not in ALLOWED_GENERATOR_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Недопустимий статус генератора: {new_status}"
                )
            old_val_str = str(gen.status)
            gen.status = new_status
        elif data.field_name == "nominal_consumption_l_per_h":
            old_val_str = str(gen.nominal_consumption_l_per_h)
            gen.nominal_consumption_l_per_h = _parse_non_negative_float(data.new_value, data.field_name)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Непідтримуване поле: {data.field_name}")

    elif target_entity_type == "FuelStock":
        stock = await db.get(FuelStock, data.entity_id)
        if not stock:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Склад ГСМ не знайдено")
        target_facility_id = stock.facility_id or target_facility_id
        target_name = f"{stock.name} ({stock.fuel_type})"

        if data.field_name == "current_balance_l":
            old_val_str = str(stock.current_balance_l)
            stock.current_balance_l = _parse_non_negative_float(data.new_value, data.field_name)
        elif data.field_name == "name":
            old_val_str = str(stock.name)
            stock.name = str(data.new_value).strip()
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Непідтримуване поле: {data.field_name}")

    elif target_entity_type == "MaintenanceSchedule":
        sched = await db.get(MaintenanceSchedule, data.entity_id)
        if not sched:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Графік ТО не знайдено")
        gen = await db.get(Generator, sched.generator_id) if sched.generator_id else None
        target_facility_id = (gen.facility_id if gen else None) or target_facility_id
        target_name = f"{sched.title or 'Графік ТО'} ({gen.name if gen else 'Генератор'})"

        if data.field_name == "interval_hours":
            old_val_str = str(sched.interval_hours)
            sched.interval_hours = _parse_non_negative_float(data.new_value, data.field_name)
        elif data.field_name == "next_due_hours":
            old_val_str = str(sched.next_due_hours)
            sched.next_due_hours = _parse_non_negative_float(data.new_value, data.field_name)
        elif data.field_name == "last_performed_hours":
            old_val_str = str(sched.last_performed_hours)
            sched.last_performed_hours = _parse_non_negative_float(data.new_value, data.field_name)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Непідтримуване поле: {data.field_name}")

    elif target_entity_type == "Facility":
        fac = await db.get(Facility, data.entity_id)
        if not fac:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Об'єкт не знайдено")
        target_facility_id = fac.id
        target_name = fac.name

        if data.field_name == "name":
            old_val_str = str(fac.name)
            fac.name = str(data.new_value).strip()
        elif data.field_name == "address":
            old_val_str = str(fac.address or "")
            fac.address = str(data.new_value).strip()
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Непідтримуване поле: {data.field_name}")

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Непідтримувана сутність для системного коригування: {target_entity_type}"
        )

    # Resolve facility name for response
    facility_name = None
    if target_facility_id:
        fac_obj = await db.get(Facility, target_facility_id)
        if fac_obj:
            facility_name = fac_obj.name

    adj = await record_system_adjustment(
        db=db,
        user_id=current_user.id,
        facility_id=target_facility_id,
        target_name=target_name,
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
        facility_id=target_facility_id,
        facility_name=facility_name,
        target_name=target_name,
        entity_type=adj.entity_type,
        entity_id=adj.entity_id,
        field_name=adj.field_name,
        old_value=adj.old_value,
        new_value=adj.new_value,
        reason=adj.reason,
        created_at=adj.created_at
    )
