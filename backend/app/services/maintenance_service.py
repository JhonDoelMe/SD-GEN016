from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.generator import Generator
from backend.app.models.maintenance import MaintenanceSchedule, MaintenanceRecord
from backend.app.schemas.maintenance import MaintenanceRecordCreate, MaintenanceScheduleOut
from backend.app.services.audit_service import log_audit


async def get_maintenance_schedule_status(db: AsyncSession, generator_id: Optional[int] = None) -> MaintenanceScheduleOut:
    gen_query = select(Generator)
    if generator_id:
        gen_query = gen_query.where(Generator.id == generator_id)
    gen_res = await db.execute(gen_query)
    generator = gen_res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    m_res = await db.execute(select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id == generator.id))
    m_sched = m_res.scalars().first()
    if not m_sched:
        m_sched = MaintenanceSchedule(
            generator_id=generator.id,
            interval_hours=300.0,
            last_performed_hours=0.0,
            next_due_hours=300.0,
            is_active=True
        )
        db.add(m_sched)
        await db.flush()
    else:
        # Auto-heal legacy schedule where last_performed was 235 and next_due was 535
        if m_sched.last_performed_hours == 235.0 and m_sched.next_due_hours > 300.0:
            m_sched.last_performed_hours = 0.0
            m_sched.next_due_hours = m_sched.interval_hours
            await db.flush()
            await db.commit()

    hours_rem = round(m_sched.next_due_hours - generator.current_operating_hours, 1)
    is_due = hours_rem <= 20.0  # Alert when within 20 operating hours
    is_overdue = hours_rem <= 0.0

    return MaintenanceScheduleOut(
        id=m_sched.id,
        generator_id=generator.id,
        interval_hours=m_sched.interval_hours,
        last_performed_hours=m_sched.last_performed_hours,
        next_due_hours=m_sched.next_due_hours,
        current_operating_hours=generator.current_operating_hours,
        hours_remaining=hours_rem,
        is_due=is_due,
        is_overdue=is_overdue,
        is_active=m_sched.is_active
    )


async def record_maintenance(
    db: AsyncSession,
    data: MaintenanceRecordCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> MaintenanceRecord:
    gen_query = select(Generator)
    if data.generator_id:
        gen_query = gen_query.where(Generator.id == data.generator_id)
    gen_res = await db.execute(gen_query)
    generator = gen_res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    record = MaintenanceRecord(
        generator_id=generator.id,
        user_id=user_id,
        maintenance_type=data.maintenance_type,
        operating_hours=generator.current_operating_hours,
        work_description=data.work_description.strip(),
        consumables_used=data.consumables_used.strip() if data.consumables_used else None,
        cost=data.cost,
        comment=data.comment.strip() if data.comment else None,
        photo_urls=data.photo_urls
    )
    db.add(record)

    # Get schedule
    m_res = await db.execute(select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id == generator.id))
    m_sched = m_res.scalars().first()

    if data.maintenance_type == "SCHEDULED":
        # Regular scheduled maintenance resets/advances the due counter
        if m_sched:
            m_sched.last_performed_hours = generator.current_operating_hours
            m_sched.next_due_hours = round(generator.current_operating_hours + m_sched.interval_hours, 1)

        # Clear MAINTENANCE_REQUIRED state if it was set
        if generator.status == "MAINTENANCE_REQUIRED":
            generator.status = "STOPPED"

    elif data.maintenance_type == "INTERMEDIATE":
        # Critical business rule: INTERMEDIATE maintenance DOES NOT advance or reset scheduled maintenance!
        # Do not modify m_sched.next_due_hours or m_sched.last_performed_hours.
        pass

    await db.flush()

    await log_audit(
        db=db,
        action=f"MAINTENANCE_{data.maintenance_type}",
        entity_type="MaintenanceRecord",
        entity_id=str(record.id),
        user_id=user_id,
        details={
            "type": data.maintenance_type,
            "operating_hours": record.operating_hours,
            "work": record.work_description,
            "cost": record.cost,
            "next_due_hours": m_sched.next_due_hours if m_sched else None
        },
        ip_address=ip_address
    )
    await db.commit()
    return record


async def recalculate_schedule(
    db: AsyncSession,
    generator_id: Optional[int] = None,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None
) -> MaintenanceScheduleOut:
    gen_query = select(Generator)
    if generator_id:
        gen_query = gen_query.where(Generator.id == generator_id)
    gen_res = await db.execute(gen_query)
    generator = gen_res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    m_res = await db.execute(select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id == generator.id))
    m_sched = m_res.scalars().first()
    if not m_sched:
        m_sched = MaintenanceSchedule(
            generator_id=generator.id,
            interval_hours=300.0,
            last_performed_hours=0.0,
            next_due_hours=300.0,
            is_active=True
        )
        db.add(m_sched)
    else:
        # Determine actual last performed scheduled maintenance from records
        records_res = await db.execute(
            select(MaintenanceRecord)
            .where(MaintenanceRecord.generator_id == generator.id, MaintenanceRecord.maintenance_type == "SCHEDULED")
            .order_by(MaintenanceRecord.operating_hours.desc())
        )
        last_rec = records_res.scalars().first()
        if last_rec:
            last_performed = last_rec.operating_hours
        else:
            last_performed = 0.0

        # Calculate next milestone
        interval = m_sched.interval_hours if m_sched.interval_hours > 0 else 300.0
        next_due = last_performed + interval
        while next_due < generator.current_operating_hours and (next_due + interval <= generator.current_operating_hours):
            next_due += interval

        m_sched.last_performed_hours = last_performed
        m_sched.next_due_hours = round(next_due, 1)

    await db.flush()

    if user_id:
        await log_audit(
            db=db,
            action="MAINTENANCE_SCHEDULE_RECALCULATED",
            entity_type="MaintenanceSchedule",
            entity_id=str(m_sched.id),
            user_id=user_id,
            details={
                "generator_id": generator.id,
                "current_hours": generator.current_operating_hours,
                "last_performed_hours": m_sched.last_performed_hours,
                "next_due_hours": m_sched.next_due_hours,
                "interval_hours": m_sched.interval_hours
            },
            ip_address=ip_address
        )
    await db.commit()

    return await get_maintenance_schedule_status(db, generator.id)

