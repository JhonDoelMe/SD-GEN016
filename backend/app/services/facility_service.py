import datetime
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.facility import Facility
from backend.app.models.generator import Generator
from backend.app.models.fuel import FuelStock
from backend.app.schemas.facility import FacilityCreate, FacilityUpdate, FacilityOut
from backend.app.services.audit_service import log_audit


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


async def get_all_facilities(db: AsyncSession) -> List[FacilityOut]:
    result = await db.execute(
        select(Facility).options(
            selectinload(Facility.generators),
            selectinload(Facility.fuel_stocks)
        ).order_by(Facility.id.asc())
    )
    facilities = result.scalars().all()

    out = []
    for f in facilities:
        out.append(
            FacilityOut(
                id=f.id,
                name=f.name,
                address=f.address,
                description=f.description,
                timezone=f.timezone,
                created_at=f.created_at,
                updated_at=f.updated_at,
                generator_count=len(f.generators),
                fuel_stock_count=len(f.fuel_stocks),
            )
        )
    return out


async def get_facility_by_id(db: AsyncSession, facility_id: int) -> FacilityOut:
    result = await db.execute(
        select(Facility).options(
            selectinload(Facility.generators),
            selectinload(Facility.fuel_stocks)
        ).where(Facility.id == facility_id)
    )
    f = result.scalars().first()
    if not f:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Об'єкт з ID {facility_id} не знайдено"
        )
    return FacilityOut(
        id=f.id,
        name=f.name,
        address=f.address,
        description=f.description,
        timezone=f.timezone,
        created_at=f.created_at,
        updated_at=f.updated_at,
        generator_count=len(f.generators),
        fuel_stock_count=len(f.fuel_stocks),
    )


async def create_facility(
    db: AsyncSession,
    data: FacilityCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> FacilityOut:
    # Check name unique
    existing = await db.execute(select(Facility).where(Facility.name == data.name.strip()))
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Об'єкт з назвою '{data.name.strip()}' вже існує"
        )

    now = utc_now()
    facility = Facility(
        name=data.name.strip(),
        address=data.address.strip() if data.address else None,
        description=data.description.strip() if data.description else None,
        timezone=data.timezone.strip() if data.timezone else "Europe/Kyiv",
        created_at=now,
        updated_at=now,
    )
    db.add(facility)
    await db.flush()

    # Automatically create a default fuel stock for this facility
    default_stock = FuelStock(
        facility_id=facility.id,
        name=f"Склад ГСМ ({facility.name})",
        fuel_type="А-95",
        current_balance_l=0.0
    )
    db.add(default_stock)
    await db.flush()

    await log_audit(
        db=db,
        action="FACILITY_CREATED",
        entity_type="Facility",
        entity_id=str(facility.id),
        user_id=user_id,
        details={"name": facility.name, "address": facility.address},
        ip_address=ip_address
    )
    await db.commit()

    return await get_facility_by_id(db, facility.id)


async def update_facility(
    db: AsyncSession,
    facility_id: int,
    data: FacilityUpdate,
    user_id: int,
    ip_address: Optional[str] = None
) -> FacilityOut:
    result = await db.execute(select(Facility).where(Facility.id == facility_id))
    facility = result.scalars().first()
    if not facility:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Об'єкт з ID {facility_id} не знайдено"
        )

    if data.name is not None and data.name.strip() != facility.name:
        existing = await db.execute(
            select(Facility).where(Facility.name == data.name.strip(), Facility.id != facility_id)
        )
        if existing.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Об'єкт з назвою '{data.name.strip()}' вже існує"
            )
        facility.name = data.name.strip()

    if data.address is not None:
        facility.address = data.address.strip() if data.address else None
    if data.description is not None:
        facility.description = data.description.strip() if data.description else None
    if data.timezone is not None:
        facility.timezone = data.timezone.strip()

    facility.updated_at = utc_now()
    await db.flush()

    await log_audit(
        db=db,
        action="FACILITY_UPDATED",
        entity_type="Facility",
        entity_id=str(facility.id),
        user_id=user_id,
        details={"name": facility.name, "address": facility.address},
        ip_address=ip_address
    )
    await db.commit()

    return await get_facility_by_id(db, facility.id)


async def delete_facility(
    db: AsyncSession,
    facility_id: int,
    user_id: int,
    ip_address: Optional[str] = None
) -> dict:
    count_res = await db.execute(select(func.count(Facility.id)))
    total_facilities = count_res.scalar() or 0
    if total_facilities <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо видалити єдиний об'єкт у системі"
        )

    result = await db.execute(
        select(Facility).options(
            selectinload(Facility.generators),
            selectinload(Facility.fuel_stocks)
        ).where(Facility.id == facility_id)
    )
    facility = result.scalars().first()
    if not facility:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Об'єкт з ID {facility_id} не знайдено"
        )

    for gen in facility.generators:
        if gen.status == "RUNNING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неможливо видалити об'єкт: генератор '{gen.name}' наразі працює!"
            )

    if facility.generators:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неможливо видалити об'єкт, на якому зареєстровано {len(facility.generators)} генератор(ів). Спочатку видаліть або перемістіть генератори."
        )

    facility_name = facility.name
    # Delete associated fuel stocks if any
    for stock in facility.fuel_stocks:
        await db.delete(stock)

    await db.delete(facility)
    await db.flush()

    await log_audit(
        db=db,
        action="FACILITY_DELETED",
        entity_type="Facility",
        entity_id=str(facility_id),
        user_id=user_id,
        details={"name": facility_name},
        ip_address=ip_address
    )
    await db.commit()

    return {"message": f"Об'єкт '{facility_name}' успішно видалено"}
