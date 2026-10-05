import datetime
from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.timezone import now_utc, is_within_work_schedule
from backend.app.models.generator import Generator, GeneratorSchedule, GeneratorRun
from backend.app.models.maintenance import MaintenanceSchedule, MaintenanceRecord
from backend.app.models.fault import Fault
from backend.app.models.fuel import FuelTransfer
from backend.app.schemas.generator import GeneratorWizardSetup, GeneratorCreate, GeneratorStopRequest
from backend.app.services.audit_service import log_audit


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


async def get_or_create_default_generator(db: AsyncSession, generator_id: Optional[int] = None, facility_id: Optional[int] = None) -> Generator:
    if generator_id:
        res = await db.execute(
            select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id)
        )
        gen = res.scalars().first()
        if gen:
            return gen

    query = select(Generator).options(selectinload(Generator.schedules))
    if facility_id:
        query = query.where(Generator.facility_id == facility_id)
    res = await db.execute(query)
    generator = res.scalars().first()
    if not generator:
        generator = Generator(
            facility_id=facility_id or 1,
            name="Бензиновий генератор 5кВт",
            model="PG-6500",
            manufacturer="PowerGen",
            serial_number="GEN-2026-001",
            rated_power_kw=5.0,
            tank_capacity_l=25.0,
            fuel_type="А-95",
            nominal_consumption_l_per_h=2.2,
            current_operating_hours=0.0,
            fuel_tank_level_l=0.0,
            status="STOPPED",
            is_configured=False,
            timezone="Europe/Kyiv",
            created_at=utc_now(),
            updated_at=utc_now()
        )
        db.add(generator)
        await db.flush()
        # Reload with schedules
        res2 = await db.execute(
            select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator.id)
        )
        generator = res2.scalars().first()
    return generator


async def setup_generator_wizard(
    db: AsyncSession,
    setup_data: GeneratorWizardSetup,
    user_id: int,
    ip_address: Optional[str] = None
) -> Generator:
    generator = await get_or_create_default_generator(db)

    generator.name = setup_data.name
    generator.model = setup_data.model
    generator.manufacturer = setup_data.manufacturer
    generator.serial_number = setup_data.serial_number
    generator.rated_power_kw = setup_data.rated_power_kw
    generator.tank_capacity_l = setup_data.tank_capacity_l
    generator.fuel_type = setup_data.fuel_type
    generator.nominal_consumption_l_per_h = setup_data.nominal_consumption_l_per_h
    generator.current_operating_hours = setup_data.initial_operating_hours
    generator.fuel_tank_level_l = min(setup_data.initial_fuel_tank_level_l, setup_data.tank_capacity_l)
    generator.timezone = setup_data.timezone
    generator.is_configured = True
    generator.status = "STOPPED"
    generator.updated_at = utc_now()

    if setup_data.facility_id:
        generator.facility_id = setup_data.facility_id

    # Clear old schedules with direct delete
    await db.execute(delete(GeneratorSchedule).where(GeneratorSchedule.generator_id == generator.id))

    new_schedule = GeneratorSchedule(
        generator_id=generator.id,
        weekday=-1,
        start_time=setup_data.work_schedule_start,
        end_time=setup_data.work_schedule_end,
        timezone=setup_data.timezone,
        is_active=True
    )
    db.add(new_schedule)

    # Configure maintenance schedule
    interval = setup_data.maintenance_interval_hours
    init_hours = setup_data.initial_operating_hours
    if setup_data.last_maintenance_performed_hours is not None:
        last_performed = setup_data.last_maintenance_performed_hours
        if last_performed >= init_hours and init_hours < interval:
            last_performed = 0.0
            next_due = interval
        else:
            next_due = last_performed + interval
            while next_due <= init_hours:
                next_due += interval
    else:
        cycle = int(init_hours // interval)
        last_performed = float(cycle * interval)
        next_due = float((cycle + 1) * interval)

    m_schedules_res = await db.execute(
        select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id == generator.id)
    )
    m_schedule = m_schedules_res.scalars().first()
    if not m_schedule:
        m_schedule = MaintenanceSchedule(
            generator_id=generator.id,
            interval_hours=interval,
            last_performed_hours=last_performed,
            next_due_hours=next_due,
            is_active=True
        )
        db.add(m_schedule)
    else:
        m_schedule.interval_hours = interval
        m_schedule.last_performed_hours = last_performed
        m_schedule.next_due_hours = next_due

    await db.flush()

    await log_audit(
        db=db,
        action="GENERATOR_WIZARD_CONFIGURED",
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=user_id,
        details={
            "name": generator.name,
            "initial_hours": generator.current_operating_hours,
            "tank_capacity": generator.tank_capacity_l,
            "schedule": f"{setup_data.work_schedule_start}-{setup_data.work_schedule_end}",
            "maint_interval": setup_data.maintenance_interval_hours,
        },
        ip_address=ip_address
    )
    await db.commit()

    # Re-fetch with schedules eagerly loaded
    res = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator.id)
    )
    return res.scalars().first()


async def start_generator(
    db: AsyncSession,
    generator_id: int,
    user_id: int,
    fuel_level_l: Optional[float] = None,
    ip_address: Optional[str] = None
) -> GeneratorRun:
    res = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id)
    )
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    if not generator.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Генератор ще не налаштований. Спочатку пройдіть майстер налаштування."
        )

    # Invariant checks on status
    if generator.status == "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо запустити генератор: генератор уже працює"
        )
    if generator.status == "BLOCKED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Генератор заблокований адміністратором. Запуск заборонено."
        )
    if generator.status == "FAULTY":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Генератор має критичну несправність. Спочатку усуньте несправність."
        )

    # Fetch active schedules explicitly
    sched_res = await db.execute(
        select(GeneratorSchedule).where(
            GeneratorSchedule.generator_id == generator.id,
            GeneratorSchedule.is_active == True
        )
    )
    schedules = sched_res.scalars().all()
    schedules_data = [
        {"weekday": s.weekday, "start_time": s.start_time, "end_time": s.end_time, "is_active": s.is_active}
        for s in schedules
    ]
    is_allowed, schedule_msg = is_within_work_schedule(schedules_data)
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Запуск відхилено сервером: {schedule_msg}"
        )

    # Determine starting fuel level
    current_fuel = fuel_level_l if fuel_level_l is not None else generator.fuel_tank_level_l
    if current_fuel is not None and current_fuel > generator.tank_capacity_l:
        current_fuel = generator.tank_capacity_l

    # Create run record
    run = GeneratorRun(
        generator_id=generator.id,
        user_id=user_id,
        start_time=utc_now(),
        start_hours=generator.current_operating_hours,
        start_fuel_level_l=current_fuel,
        status="RUNNING"
    )
    db.add(run)

    generator.status = "RUNNING"
    if current_fuel is not None:
        generator.fuel_tank_level_l = current_fuel

    await db.flush()

    await log_audit(
        db=db,
        action="GENERATOR_START",
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=user_id,
        details={
            "start_hours": run.start_hours,
            "start_fuel": current_fuel,
            "run_id": run.id
        },
        ip_address=ip_address
    )
    await db.commit()
    return run


async def stop_generator(
    db: AsyncSession,
    generator_id: int,
    user_id: int,
    stop_data: GeneratorStopRequest,
    ip_address: Optional[str] = None
) -> GeneratorRun:
    res = await db.execute(
        select(Generator).where(Generator.id == generator_id)
    )
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    if generator.status != "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо зупинити генератор: генератор не перебуває у стані 'Працює'"
        )

    # Find the active run
    run_res = await db.execute(
        select(GeneratorRun)
        .where(GeneratorRun.generator_id == generator.id, GeneratorRun.status == "RUNNING")
        .order_by(GeneratorRun.id.desc())
    )
    run = run_res.scalars().first()
    if not run:
        run = GeneratorRun(
            generator_id=generator.id,
            user_id=user_id,
            start_time=generator.updated_at,
            start_hours=generator.current_operating_hours,
            status="RUNNING"
        )
        db.add(run)
        await db.flush()

    end_time = utc_now()
    elapsed_seconds = max(1, int((end_time - run.start_time).total_seconds()))

    if stop_data.end_hours is not None:
        if stop_data.end_hours < run.start_hours:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Кінцеві мотогодини ({stop_data.end_hours}) не можуть бути меншими за початкові ({run.start_hours})"
            )
        if stop_data.end_hours > run.start_hours:
            # Operator entered advanced counter value
            end_hours = stop_data.end_hours
            duration_hours = round(end_hours - run.start_hours, 2)
            duration_seconds = max(elapsed_seconds, int(round(duration_hours * 3600)))
            calculated_consumption = round(duration_hours * generator.nominal_consumption_l_per_h, 2)
        else:
            # Operator entered same counter value (very short run)
            duration_seconds = elapsed_seconds
            duration_hours = round(duration_seconds / 3600.0, 4)
            end_hours = round(run.start_hours + duration_hours, 3)
            calculated_consumption = round((duration_seconds / 3600.0) * generator.nominal_consumption_l_per_h, 3)
    else:
        # Automatic calculation from elapsed wall-clock seconds
        duration_seconds = elapsed_seconds
        duration_hours = round(duration_seconds / 3600.0, 4)
        end_hours = round(run.start_hours + duration_hours, 3)
        calculated_consumption = round((duration_seconds / 3600.0) * generator.nominal_consumption_l_per_h, 3)

    run.end_time = end_time
    run.end_hours = end_hours
    run.duration_seconds = duration_seconds
    run.duration_hours = duration_hours
    run.calculated_consumption_l = calculated_consumption
    run.status = "COMPLETED"
    run.note = stop_data.note

    # Update generator metrics
    generator.current_operating_hours = end_hours
    generator.updated_at = end_time

    if stop_data.end_fuel_level_l is not None:
        generator.fuel_tank_level_l = max(0.0, min(stop_data.end_fuel_level_l, generator.tank_capacity_l))
        run.end_fuel_level_l = generator.fuel_tank_level_l
    else:
        # Deduct calculated consumption from tank level
        new_level = max(0.0, generator.fuel_tank_level_l - calculated_consumption)
        generator.fuel_tank_level_l = round(new_level, 3)
        run.end_fuel_level_l = generator.fuel_tank_level_l

    # Check maintenance status
    m_res = await db.execute(
        select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id == generator.id)
    )
    m_sched = m_res.scalars().first()
    if m_sched and m_sched.is_active and generator.current_operating_hours >= m_sched.next_due_hours:
        generator.status = "MAINTENANCE_REQUIRED"
    else:
        generator.status = "STOPPED"

    await db.flush()

    h = duration_seconds // 3600
    m = (duration_seconds % 3600) // 60
    s = duration_seconds % 60
    duration_formatted = f"{h:02d}:{m:02d}:{s:02d}"

    await log_audit(
        db=db,
        action="GENERATOR_STOP",
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=user_id,
        details={
            "end_hours": run.end_hours,
            "duration_seconds": duration_seconds,
            "duration_formatted": duration_formatted,
            "duration_hours": duration_hours,
            "calculated_consumption_l": calculated_consumption,
            "end_fuel_level_l": generator.fuel_tank_level_l,
            "run_id": run.id,
            "status_after": generator.status
        },
        ip_address=ip_address
    )
    await db.commit()
    return run


async def get_generators_list(db: AsyncSession, facility_id: Optional[int] = None) -> List[Generator]:
    query = select(Generator).options(selectinload(Generator.schedules))
    if facility_id:
        query = query.where(Generator.facility_id == facility_id)
    query = query.order_by(Generator.id.asc())
    res = await db.execute(query)
    generators = res.scalars().all()
    if not generators and (facility_id is None or facility_id == 1):
        default_gen = await get_or_create_default_generator(db, facility_id=facility_id)
        return [default_gen]
    return list(generators)


async def create_generator(
    db: AsyncSession,
    setup_data: GeneratorCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> Generator:
    facility_id = setup_data.facility_id or 1
    generator = Generator(
        facility_id=facility_id,
        name=setup_data.name.strip(),
        model=setup_data.model.strip(),
        manufacturer=setup_data.manufacturer.strip(),
        serial_number=setup_data.serial_number.strip(),
        rated_power_kw=setup_data.rated_power_kw,
        tank_capacity_l=setup_data.tank_capacity_l,
        fuel_type=setup_data.fuel_type.strip(),
        nominal_consumption_l_per_h=setup_data.nominal_consumption_l_per_h,
        current_operating_hours=setup_data.initial_operating_hours,
        fuel_tank_level_l=min(setup_data.initial_fuel_tank_level_l, setup_data.tank_capacity_l),
        timezone=setup_data.timezone.strip() if setup_data.timezone else "Europe/Kyiv",
        is_configured=True,
        status="STOPPED",
        created_at=utc_now(),
        updated_at=utc_now()
    )
    db.add(generator)
    await db.flush()

    new_schedule = GeneratorSchedule(
        generator_id=generator.id,
        weekday=-1,
        start_time=setup_data.work_schedule_start,
        end_time=setup_data.work_schedule_end,
        timezone=generator.timezone,
        is_active=True
    )
    db.add(new_schedule)

    interval = setup_data.maintenance_interval_hours
    init_hours = setup_data.initial_operating_hours
    if setup_data.last_maintenance_performed_hours is not None:
        last_performed = setup_data.last_maintenance_performed_hours
        if last_performed >= init_hours and init_hours < interval:
            last_performed = 0.0
            next_due = interval
        else:
            next_due = last_performed + interval
            while next_due <= init_hours:
                next_due += interval
    else:
        last_performed = 0.0
        next_due = interval
        while next_due <= init_hours:
            last_performed = next_due
            next_due += interval

    m_schedule = MaintenanceSchedule(
        generator_id=generator.id,
        interval_hours=interval,
        last_performed_hours=last_performed,
        next_due_hours=next_due,
        is_active=True
    )
    db.add(m_schedule)
    await db.flush()

    await log_audit(
        db=db,
        action="GENERATOR_CREATED",
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=user_id,
        details={
            "name": generator.name,
            "facility_id": facility_id,
            "initial_hours": generator.current_operating_hours,
            "tank_capacity_l": generator.tank_capacity_l
        },
        ip_address=ip_address
    )
    await db.commit()

    res = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator.id)
    )
    return res.scalars().first()


async def delete_generator(
    db: AsyncSession,
    generator_id: int,
    user_id: int,
    ip_address: Optional[str] = None
) -> dict:
    res = await db.execute(select(Generator).where(Generator.id == generator_id))
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    if generator.status == "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо видалити генератор, який зараз працює! Спочатку зупиніть генератор."
        )

    gen_name = generator.name

    # Cascade delete generator and all associated relations (runs, schedules, maintenance, faults, transfers)
    await db.delete(generator)
    await db.flush()

    await log_audit(
        db=db,
        action="GENERATOR_DELETED",
        entity_type="Generator",
        entity_id=str(generator_id),
        user_id=user_id,
        details={"name": gen_name, "model": generator.model, "serial_number": generator.serial_number},
        ip_address=ip_address
    )
    await db.commit()

    return {"message": f"Генератор '{gen_name}' (ID {generator_id}) успішно видалено"}
