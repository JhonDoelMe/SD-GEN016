from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.timezone import now_utc
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.models.fault import Fault
from backend.app.schemas.fault import FaultCreate, FaultStatusUpdate
from backend.app.services.audit_service import log_audit
from backend.app.services.generator_service import (
    stop_generator,
    _evaluate_generator_resting_status,
)


async def _resolve_fault_generator(
    db: AsyncSession,
    generator_id: Optional[int],
    facility_id: Optional[int] = None,
) -> Generator:
    if generator_id is not None:
        generator = await db.get(Generator, generator_id)
        if not generator:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")
        if not getattr(generator, "is_active", True) or generator.status == "ARCHIVED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неможливо зареєструвати несправність для архівованого генератора",
            )
        if facility_id is not None and generator.facility_id != facility_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступ заборонено: генератор закріплений за іншим об'єктом",
            )
        return generator

    q = select(Generator).where(Generator.is_active == True)  # noqa: E712
    if facility_id is not None:
        q = q.where(Generator.facility_id == facility_id)
    gens = list((await db.execute(q.order_by(Generator.id.asc()))).scalars().all())
    if not gens:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")
    if len(gens) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Оберіть конкретний генератор (generator_id), оскільки в області доступу знайдено декілька активних генераторів",
        )
    return gens[0]


async def create_fault(
    db: AsyncSession,
    fault_data: FaultCreate,
    user_id: int,
    ip_address: Optional[str] = None,
    facility_id: Optional[int] = None,
) -> Fault:
    generator = await _resolve_fault_generator(db, fault_data.generator_id, facility_id=facility_id)

    # If critical fault is reported while generator is RUNNING, safely stop the active session first
    if fault_data.priority == "CRITICAL":
        active_run_res = await db.execute(
            select(GeneratorRun).where(
                GeneratorRun.generator_id == generator.id,
                GeneratorRun.status == "RUNNING",
            )
        )
        if active_run_res.scalars().first() is not None or generator.status == "RUNNING":
            try:
                await stop_generator(
                    db=db,
                    generator_id=generator.id,
                    user_id=user_id,
                    reason="CRITICAL_FAULT",
                    system_note=f"Аварійна зупинка через реєстрацію критичної несправності: {fault_data.title.strip()}",
                    actor_type="SYSTEM_GUARD",
                    ip_address=ip_address,
                    facility_id=facility_id,
                )
            except Exception as stop_err:
                print(f"[FAULT] Notice during auto-stop on critical fault: {stop_err}", flush=True)

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
            "generator_id": generator.id,
            "facility_id": generator.facility_id,
            "title": fault.title,
            "priority": fault.priority,
            "operating_hours": fault.operating_hours,
            "generator_status_after": generator.status
        },
        ip_address=ip_address
    )
    await db.commit()

    if fault_data.priority == "CRITICAL":
        try:
            from backend.app.services.notification_service import notify_critical_fault
            await notify_critical_fault(
                db=db,
                generator=generator,
                fault_title=fault.title,
                fault_description=fault.description
            )
        except Exception as ex:
            print(f"[NOTIF] Failed to send critical fault notification: {ex}", flush=True)

    q_fresh = (
        select(Fault)
        .options(selectinload(Fault.user), selectinload(Fault.resolved_by))
        .where(Fault.id == fault.id)
    )
    res_fresh = await db.execute(q_fresh)
    return res_fresh.scalar_one()


async def update_fault_status(
    db: AsyncSession,
    fault_id: int,
    status_data: FaultStatusUpdate,
    user_id: int,
    ip_address: Optional[str] = None
) -> Fault:
    q = (
        select(Fault)
        .options(selectinload(Fault.user), selectinload(Fault.resolved_by))
        .where(Fault.id == fault_id)
    )
    res = await db.execute(q)
    fault = res.scalar_one_or_none()
    if not fault:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Несправність не знайдена")

    old_status = fault.status
    fault.status = status_data.status

    if status_data.resolution_notes is not None:
        fault.resolution_notes = status_data.resolution_notes.strip()

    generator = await db.get(Generator, fault.generator_id)

    if status_data.status in ("RESOLVED", "CLOSED"):
        fault.resolved_by_id = user_id
        fault.resolved_at = now_utc(naive=True)

        # Flush so the query below sees this fault as RESOLVED/CLOSED
        await db.flush()

        # Re-evaluate generator status if it was FAULTY and no other open CRITICAL faults remain
        if generator and generator.status == "FAULTY":
            generator.status = "STOPPED"
            generator.status = await _evaluate_generator_resting_status(db, generator)

    elif status_data.status in ("OPEN", "NEW", "IN_PROGRESS", "ACCEPTED", "PENDING"):
        fault.resolved_by_id = None
        fault.resolved_at = None

        if fault.priority == "CRITICAL" and generator and generator.status not in ("RUNNING", "ARCHIVED"):
            generator.status = "FAULTY"

    await db.flush()

    await log_audit(
        db=db,
        action="FAULT_STATUS_UPDATED",
        entity_type="Fault",
        entity_id=str(fault.id),
        user_id=user_id,
        details={
            "generator_id": fault.generator_id,
            "old_status": old_status,
            "new_status": fault.status,
            "resolution_notes": fault.resolution_notes,
            "generator_status_after": generator.status if generator else None,
        },
        ip_address=ip_address
    )
    await db.commit()

    # Re-fetch with fresh relationships
    q_fresh = (
        select(Fault)
        .options(selectinload(Fault.user), selectinload(Fault.resolved_by))
        .where(Fault.id == fault.id)
    )
    res_fresh = await db.execute(q_fresh)
    return res_fresh.scalar_one()
