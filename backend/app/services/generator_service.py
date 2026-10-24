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
from backend.app.models.facility import Facility
from backend.app.schemas.generator import GeneratorWizardSetup, GeneratorCreate, GeneratorStopRequest, GeneratorUpdate, GeneratorManualRunCreate
from backend.app.services.audit_service import log_audit


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


async def get_or_create_default_generator(db: AsyncSession, generator_id: Optional[int] = None, facility_id: Optional[int] = None) -> Generator:
    if generator_id is not None:
        query = select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id)
        if facility_id is not None:
            query = query.where(Generator.facility_id == facility_id)
        res = await db.execute(query)
        gen = res.scalars().first()
        if not gen:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Генератор не знайдено"
            )
        return gen

    query = select(Generator).options(selectinload(Generator.schedules))
    if facility_id:
        query = query.where(Generator.facility_id == facility_id)
    query = query.order_by(Generator.id.asc())
    res = await db.execute(query)
    generator = res.scalars().first()
    if not generator:
        target_fac_id = facility_id
        if target_fac_id:
            fac_check = await db.execute(select(Facility.id).where(Facility.id == target_fac_id))
            if not fac_check.scalars().first():
                target_fac_id = None
        if not target_fac_id:
            fac_res = await db.execute(select(Facility.id).order_by(Facility.id.asc()))
            first_fac = fac_res.scalars().first()
            target_fac_id = first_fac if first_fac else 1

        generator = Generator(
            facility_id=target_fac_id,
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
            is_configured=True,
            timezone="Europe/Kyiv",
            created_at=utc_now(),
            updated_at=utc_now()
        )
        db.add(generator)
        await db.flush()

        db.add(GeneratorSchedule(
            generator_id=generator.id,
            weekday=-1,
            start_time="08:00",
            end_time="20:00",
            timezone="Europe/Kyiv",
            is_active=True
        ))
        db.add(MaintenanceSchedule(
            generator_id=generator.id,
            interval_hours=300.0,
            last_performed_hours=0.0,
            next_due_hours=300.0,
            is_active=True
        ))
        await db.flush()

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
        generator.is_configured = True
        await db.flush()

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

    # Dispatch push notification in background
    try:
        from backend.app.services.notification_service import notify_generator_start
        from backend.app.models.user import User
        u_res = await db.execute(select(User.full_name).where(User.id == user_id))
        u_name = u_res.scalar() or "Оператор"
        await notify_generator_start(
            db=db,
            generator=generator,
            user_name=u_name,
            start_fuel=current_fuel or 0.0,
            start_hours=run.start_hours
        )
    except Exception as ex:
        print(f"[NOTIF] Failed to send start notification: {ex}", flush=True)

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

            # Typo Guard ("Запобіжник опечатки мотогодин"):
            elapsed_hours = elapsed_seconds / 3600.0
            is_suspicious = (duration_hours > 14.0) or (elapsed_seconds >= 60 and abs(duration_hours - elapsed_hours) > 2.0)
            if is_suspicious and not stop_data.force_confirm:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Запобіжник опечатки: напрацювання за лічильником ({duration_hours:.2f} год) суттєво відрізняється "
                        f"від часу роботи за таймером ({elapsed_hours:.2f} год). "
                        f"Перевірте введені мотогодини або встановіть підтвердження."
                    )
                )
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
        generator.fuel_tank_level_l = min(stop_data.end_fuel_level_l, generator.tank_capacity_l)
        run.end_fuel_level_l = generator.fuel_tank_level_l
    else:
        # Deduct calculated consumption from tank level (allows negative balance to show real fuel deficit)
        new_level = generator.fuel_tank_level_l - calculated_consumption
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

    # Dispatch push notification in background
    try:
        from backend.app.services.notification_service import notify_generator_stop
        from backend.app.models.user import User
        u_res = await db.execute(select(User.full_name).where(User.id == user_id))
        u_name = u_res.scalar() or "Оператор"
        await notify_generator_stop(
            db=db,
            generator=generator,
            user_name=u_name,
            duration_str=duration_formatted,
            consumption_l=calculated_consumption,
            end_fuel=generator.fuel_tank_level_l
        )
    except Exception as ex:
        print(f"[NOTIF] Failed to send stop notification: {ex}", flush=True)

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
    facility_id = setup_data.facility_id
    if not facility_id:
        fac_res = await db.execute(select(Facility.id).order_by(Facility.id.asc()))
        first_fac = fac_res.scalars().first()
        facility_id = first_fac if first_fac else 1
    else:
        fac_check = await db.execute(select(Facility.id).where(Facility.id == facility_id))
        if not fac_check.scalars().first():
            fac_res = await db.execute(select(Facility.id).order_by(Facility.id.asc()))
            first_fac = fac_res.scalars().first()
            facility_id = first_fac if first_fac else 1
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


async def update_generator(
    db: AsyncSession,
    generator_id: int,
    data: GeneratorUpdate,
    user_id: int,
    ip_address: Optional[str] = None
) -> Generator:
    res = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id)
    )
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    changes = {}

    if data.facility_id is not None and data.facility_id != generator.facility_id:
        fac_check = await db.execute(select(Facility).where(Facility.id == data.facility_id))
        if not fac_check.scalars().first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Вказаний об'єкт не знайдено")
        changes["facility_id"] = (generator.facility_id, data.facility_id)
        generator.facility_id = data.facility_id

    if data.name is not None and data.name.strip():
        new_name = data.name.strip()
        if new_name != generator.name:
            changes["name"] = (generator.name, new_name)
            generator.name = new_name

    if data.model is not None and data.model.strip():
        new_model = data.model.strip()
        if new_model != generator.model:
            changes["model"] = (generator.model, new_model)
            generator.model = new_model

    if data.manufacturer is not None and data.manufacturer.strip():
        new_mfg = data.manufacturer.strip()
        if new_mfg != generator.manufacturer:
            changes["manufacturer"] = (generator.manufacturer, new_mfg)
            generator.manufacturer = new_mfg

    if data.serial_number is not None and data.serial_number.strip():
        new_sn = data.serial_number.strip()
        if new_sn != generator.serial_number:
            changes["serial_number"] = (generator.serial_number, new_sn)
            generator.serial_number = new_sn

    if data.rated_power_kw is not None and data.rated_power_kw > 0:
        if data.rated_power_kw != generator.rated_power_kw:
            changes["rated_power_kw"] = (generator.rated_power_kw, data.rated_power_kw)
            generator.rated_power_kw = data.rated_power_kw

    if data.tank_capacity_l is not None and data.tank_capacity_l > 0:
        if data.tank_capacity_l != generator.tank_capacity_l:
            changes["tank_capacity_l"] = (generator.tank_capacity_l, data.tank_capacity_l)
            generator.tank_capacity_l = data.tank_capacity_l

    if data.fuel_type is not None and data.fuel_type.strip():
        new_ft = data.fuel_type.strip()
        if new_ft != generator.fuel_type:
            changes["fuel_type"] = (generator.fuel_type, new_ft)
            generator.fuel_type = new_ft

    if data.nominal_consumption_l_per_h is not None and data.nominal_consumption_l_per_h > 0:
        if data.nominal_consumption_l_per_h != generator.nominal_consumption_l_per_h:
            changes["nominal_consumption_l_per_h"] = (generator.nominal_consumption_l_per_h, data.nominal_consumption_l_per_h)
            generator.nominal_consumption_l_per_h = data.nominal_consumption_l_per_h

    if data.timezone is not None and data.timezone.strip():
        new_tz = data.timezone.strip()
        if new_tz != generator.timezone:
            changes["timezone"] = (generator.timezone, new_tz)
            generator.timezone = new_tz

    generator.updated_at = utc_now()
    await db.flush()

    if changes:
        await log_audit(
            db=db,
            action="GENERATOR_UPDATED",
            entity_type="Generator",
            entity_id=str(generator.id),
            user_id=user_id,
            details={"changes": {k: {"old": str(v[0]), "new": str(v[1])} for k, v in changes.items()}},
            ip_address=ip_address
        )
        await db.commit()

    res = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator.id)
    )
    return res.scalars().first()



async def add_manual_run(
    db: AsyncSession,
    generator_id: int,
    user_id: int,
    data: GeneratorManualRunCreate,
    ip_address: Optional[str] = None
) -> GeneratorRun:
    res = await db.execute(select(Generator).where(Generator.id == generator_id))
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    if data.start_time >= data.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Час завершення роботи має бути пізнішим за час запуску"
        )

    # Convert to naive UTC for storage consistency
    start_dt = data.start_time.astimezone(datetime.timezone.utc).replace(tzinfo=None) if data.start_time.tzinfo else data.start_time
    end_dt = data.end_time.astimezone(datetime.timezone.utc).replace(tzinfo=None) if data.end_time.tzinfo else data.end_time

    # Calculate duration
    duration_seconds = max(1, int((end_dt - start_dt).total_seconds()))
    duration_hours = round(duration_seconds / 3600.0, 3)

    # Operating hours
    start_hours = data.start_hours if data.start_hours is not None else generator.current_operating_hours
    if data.end_hours is not None:
        if data.end_hours < start_hours:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Кінцеві мотогодини ({data.end_hours}) не можуть бути меншими за початкові ({start_hours})"
            )
        end_hours = data.end_hours
        hours_worked = round(end_hours - start_hours, 2)
        if hours_worked > 0:
            duration_hours = hours_worked

        # Typo Guard for manual log entries:
        time_diff_hours = duration_seconds / 3600.0
        is_suspicious_manual = (hours_worked > 24.0) or (abs(hours_worked - time_diff_hours) > 3.0)
        if is_suspicious_manual and not data.force_confirm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Запобіжник опечатки: напрацювання за лічильником ({hours_worked:.2f} год) суттєво розходиться "
                    f"із часовим інтервалом запису ({time_diff_hours:.2f} год). "
                    f"Перевірте мотогодини або підтвердіть дію."
                )
            )
    else:
        end_hours = round(start_hours + duration_hours, 2)

    # Fuel consumption
    if data.fuel_consumed_l is not None:
        calculated_consumption = round(data.fuel_consumed_l, 2)
    else:
        calculated_consumption = round(duration_hours * generator.nominal_consumption_l_per_h, 3)

    start_fuel = generator.fuel_tank_level_l
    # Deduct consumption from tank level (allows negative balance to show real fuel deficit)
    new_fuel_level = round(generator.fuel_tank_level_l - calculated_consumption, 2)

    # Create run record
    run = GeneratorRun(
        generator_id=generator.id,
        user_id=user_id,
        start_time=start_dt,
        end_time=end_dt,
        start_hours=start_hours,
        end_hours=end_hours,
        duration_seconds=duration_seconds,
        duration_hours=duration_hours,
        start_fuel_level_l=start_fuel,
        end_fuel_level_l=new_fuel_level,
        calculated_consumption_l=calculated_consumption,
        status="COMPLETED",
        note=data.note.strip() if data.note else "Внесено вручну (запис з паперового журналу)"
    )
    db.add(run)

    # Update generator metrics
    generator.current_operating_hours = max(generator.current_operating_hours, end_hours)
    generator.fuel_tank_level_l = new_fuel_level
    generator.updated_at = utc_now()

    # Check maintenance status
    m_res = await db.execute(
        select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id == generator.id)
    )
    m_sched = m_res.scalars().first()
    if m_sched and m_sched.is_active and generator.current_operating_hours >= m_sched.next_due_hours:
        generator.status = "MAINTENANCE_REQUIRED"

    await db.flush()

    h = duration_seconds // 3600
    m = (duration_seconds % 3600) // 60
    s = duration_seconds % 60
    duration_formatted = f"{h:02d}:{m:02d}:{s:02d}"

    await log_audit(
        db=db,
        action="GENERATOR_MANUAL_RUN_ADDED",
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=user_id,
        details={
            "run_id": run.id,
            "start_time": str(start_dt),
            "end_time": str(end_dt),
            "duration_formatted": duration_formatted,
            "duration_hours": duration_hours,
            "calculated_consumption_l": calculated_consumption,
            "new_operating_hours": generator.current_operating_hours,
            "new_fuel_tank_level_l": generator.fuel_tank_level_l,
            "note": run.note
        },
        ip_address=ip_address
    )
    await db.commit()

    q_fresh = (
        select(GeneratorRun)
        .options(selectinload(GeneratorRun.user))
        .where(GeneratorRun.id == run.id)
    )
    res_fresh = await db.execute(q_fresh)
    return res_fresh.scalar_one()
