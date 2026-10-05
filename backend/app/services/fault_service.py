from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.timezone import now_utc
from backend.app.models.generator import Generator
from backend.app.models.fault import Fault
from backend.app.schemas.fault import FaultCreate, FaultStatusUpdate
from backend.app.services.audit_service import log_audit


async def create_fault(
    db: AsyncSession,
    fault_data: FaultCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> Fault:
    gen_res = await db.execute(select(Generator))
    generator = await db.get(Generator, fault_data.generator_id) if fault_data.generator_id else gen_res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    fault = Fault(
        generator_id=generator.id,
        user_id=user_id,
        title=fault_data.title.strip(),
        description=fault_data.description.strip(),
        operating_hours=generator.current_operating_hours,
        priority=fault_data.priority,
        status="NEW",
        photo_urls=fault_data.photo_urls
    )
    db.add(fault)

    # If critical fault reported, mark generator as FAULTY
    if fault_data.priority == "CRITICAL":
        generator.status = "FAULTY"

    await db.flush()

    await log_audit(
        db=db,
        action="FAULT_REPORTED",
        entity_type="Fault",
        entity_id=str(fault.id),
        user_id=user_id,
        details={
            "title": fault.title,
            "priority": fault.priority,
            "operating_hours": fault.operating_hours,
            "generator_status_after": generator.status
        },
        ip_address=ip_address
    )
    await db.commit()
    return fault


async def update_fault_status(
    db: AsyncSession,
    fault_id: int,
    status_data: FaultStatusUpdate,
    user_id: int,
    ip_address: Optional[str] = None
) -> Fault:
    fault = await db.get(Fault, fault_id)
    if not fault:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Несправність не знайдена")

    old_status = fault.status
    fault.status = status_data.status

    if status_data.resolution_notes:
        fault.resolution_notes = status_data.resolution_notes.strip()

    if status_data.status in ("RESOLVED", "CLOSED"):
        fault.resolved_by_id = user_id
        fault.resolved_at = now_utc()

        # If generator was marked FAULTY, check if there are other open CRITICAL faults
        generator = await db.get(Generator, fault.generator_id)
        if generator and generator.status == "FAULTY":
            other_critical = await db.execute(
                select(Fault).where(
                    Fault.generator_id == generator.id,
                    Fault.priority == "CRITICAL",
                    Fault.status.notin_(["RESOLVED", "CLOSED"]),
                    Fault.id != fault.id
                )
            )
            if not other_critical.scalars().first():
                generator.status = "STOPPED"

    await db.flush()

    await log_audit(
        db=db,
        action="FAULT_STATUS_UPDATED",
        entity_type="Fault",
        entity_id=str(fault.id),
        user_id=user_id,
        details={
            "old_status": old_status,
            "new_status": fault.status,
            "resolution_notes": fault.resolution_notes
        },
        ip_address=ip_address
    )
    await db.commit()
    return fault
