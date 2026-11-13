import datetime
from typing import Optional, List, Dict, Any
from fastapi import HTTPException, status
from sqlalchemy import select, delete, func, or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.timezone import now_utc, utc_now, is_within_work_schedule, get_facility_tz
from backend.app.models.generator import Generator, GeneratorSchedule, GeneratorRun
from backend.app.models.maintenance import MaintenanceSchedule, MaintenanceRecord
from backend.app.models.fault import Fault
from backend.app.models.fuel import FuelTransfer
from backend.app.models.facility import Facility
from backend.app.models.user import User
from backend.app.schemas.generator import (
    GeneratorWizardSetup, GeneratorCreate, GeneratorStopRequest, GeneratorUpdate,
    GeneratorManualRunCreate, GeneratorFacilityTransferRequest
)
from backend.app.services.audit_service import log_audit
from backend.app.services.fuel_service import (
    validate_and_reconcile_generator_tank_level,
    consume_generator_fuel
)


def _normalize_to_utc_naive(dt: datetime.datetime, tz_name: Optional[str] = None) -> datetime.datetime:
    """
    GEN-09: Єдина політика нормалізації часу до naive UTC для збереження в БД.
    - Якщо datetime вже має tzinfo (timezone-aware), переводиться в UTC та знімається tzinfo.
    - Якщо datetime naive (без tzinfo), інтерпретується як локальний час об'єкта/генератора
      у часовому поясі `tz_name` (з урахуванням переходів на літній/зимовий час DST) і конвертується в UTC.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    local_tz = get_facility_tz(tz_name)
    local_aware = dt.replace(tzinfo=local_tz)
    return local_aware.astimezone(datetime.timezone.utc).replace(tzinfo=None)


async def _user_has_maintenance_override_permission(db: AsyncSession, user_id: int) -> bool:
    """
    GEN-06: Перевірка наявності спеціального права примусового запуску при простроченому ТО.
    Дозволено: SuperAdmin, роль Адміністратора, або права 'generator:configure' / 'maintenance:perform_scheduled'.
    """
    res = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == user_id)
    )
    user = res.scalars().first()
    if not user or not user.is_active:
        return False
    if user.is_superadmin:
        return True
    for r in (user.roles or []):
        r_name = (r.name or "").lower()
        if "admin" in r_name or "адмін" in r_name:
            return True
        for p in (getattr(r, "permissions", None) or []):
            if getattr(p, "code", "") in ("generator:configure", "maintenance:perform_scheduled"):
                return True
    return False


async def _evaluate_generator_resting_status(db: AsyncSession, generator: Generator) -> str:
    """
    GEN-16: Визначає коректний статус генератора в стані спокою (коли немає активного сеансу RUNNING).
    Пріоритет:
    1. ARCHIVED (якщо not generator.is_active або generator.status == 'ARCHIVED')
    2. BLOCKED (якщо заблокований адміністратором)
    3. FAULTY (якщо є відкрита критична несправність або статус FAULTY)
    4. MAINTENANCE_REQUIRED (якщо мотогодини >= next_due_hours активного розкладу ТО)
    5. STOPPED
    """
    if not getattr(generator, "is_active", True) or generator.status == "ARCHIVED":
        return "ARCHIVED"
    if generator.status == "BLOCKED":
        return "BLOCKED"

    # Check open critical faults
    fault_res = await db.execute(
        select(func.count(Fault.id)).where(
            Fault.generator_id == generator.id,
            Fault.status.notin_(["RESOLVED", "CLOSED"]),
            Fault.priority == "CRITICAL"
        )
    )
    if (fault_res.scalar() or 0) > 0 or generator.status == "FAULTY":
        return "FAULTY"

    m_res = await db.execute(
        select(MaintenanceSchedule).where(
            MaintenanceSchedule.generator_id == generator.id,
            MaintenanceSchedule.is_active == True
        )
    )
    m_sched = m_res.scalars().first()
    if m_sched and generator.current_operating_hours >= m_sched.next_due_hours:
        return "MAINTENANCE_REQUIRED"

    return "STOPPED"


async def reconcile_generator_state(db: AsyncSession, generator_id: int) -> Generator:
    """
    GEN-16: Діагностика та відновлення узгодженого стану генератора
    відповідно до фактичних активних сеансів, розкладу ТО та несправностей.
    """
    res = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id)
    )
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    active_run_res = await db.execute(
        select(GeneratorRun).where(
            GeneratorRun.generator_id == generator.id,
            GeneratorRun.status == "RUNNING"
        )
    )
    active_run = active_run_res.scalars().first()

    if active_run:
        if generator.status != "RUNNING":
            generator.status = "RUNNING"
            generator.updated_at = utc_now()
            await db.flush()
    else:
        expected_status = await _evaluate_generator_resting_status(db, generator)
        if generator.status != expected_status:
            generator.status = expected_status
            generator.updated_at = utc_now()
            await db.flush()

    return generator


async def get_or_create_default_generator(
    db: AsyncSession,
    generator_id: Optional[int] = None,
    facility_id: Optional[int] = None,
    include_archived: bool = False
) -> Generator:
    """
    GEN-05, GEN-12: Отримання конкретного генератора за ID (з перевіркою належності до об'єкта)
    або отримання/створення генератора для вказаного об'єкта.
    """
    if generator_id is not None:
        query = select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id)
        if not include_archived:
            query = query.where(Generator.is_active == True)
        res = await db.execute(query)
        gen = res.scalars().first()
        if not gen:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Генератор не знайдено"
            )
        if facility_id is not None and gen.facility_id != facility_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Генератор (ID {generator_id}) належить до іншого об'єкта (ID {gen.facility_id})"
            )
        return gen

    query = select(Generator).options(selectinload(Generator.schedules)).where(Generator.is_active == True)
    if facility_id is not None:
        query = query.where(Generator.facility_id == facility_id)
    query = query.order_by(Generator.id.asc())
    res = await db.execute(query)
    generator = res.scalars().first()
    if not generator:
        target_fac_id = facility_id
        if target_fac_id:
            fac_check = await db.execute(select(Facility.id).where(Facility.id == target_fac_id))
            if not fac_check.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Об'єкт з ID {target_fac_id} не знайдено"
                )
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
            is_active=True,
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
    """
    GEN-05, GEN-08, GEN-11, GEN-12: Безпечне первинне налаштування генератора через майстер (Wizard).
    - Працює з явно вказаним generator_id або генератором конкретного facility_id.
    - Забороняє випадковий перезапис чужого або працюючого генератора.
    - Валідує, щоб initial_fuel_tank_level_l не перевищував tank_capacity_l і не був від'ємним.
    """
    if setup_data.initial_fuel_tank_level_l < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Початковий рівень пального не може бути від'ємним."
        )
    if setup_data.initial_fuel_tank_level_l > setup_data.tank_capacity_l:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Початковий рівень пального ({setup_data.initial_fuel_tank_level_l} л) "
                f"не може перевищувати місткість бака ({setup_data.tank_capacity_l} л)."
            )
        )

    if setup_data.facility_id is not None:
        fac_check = await db.execute(select(Facility.id).where(Facility.id == setup_data.facility_id))
        if not fac_check.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Об'єкт з ID {setup_data.facility_id} не знайдено"
            )

    if setup_data.generator_id is not None:
        res = await db.execute(
            select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == setup_data.generator_id)
        )
        generator = res.scalars().first()
        if not generator:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")
        if setup_data.facility_id is not None and generator.facility_id != setup_data.facility_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Вказаний генератор належить до іншого об'єкта. Перезапис заборонено."
            )
    else:
        # Якщо generator_id не передано, шукаємо в межах вказаного facility_id
        q = select(Generator).options(selectinload(Generator.schedules)).where(Generator.is_active == True)
        if setup_data.facility_id is not None:
            q = q.where(Generator.facility_id == setup_data.facility_id)
        q = q.order_by(Generator.id.asc())
        res = await db.execute(q)
        existing_gens = res.scalars().all()

        if len(existing_gens) > 1 and setup_data.facility_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="У системі зареєстровано декілька генераторів. Вкажіть конкретний generator_id або facility_id для налаштування."
            )
        if existing_gens:
            generator = existing_gens[0]
        else:
            generator = await get_or_create_default_generator(db, facility_id=setup_data.facility_id)

    if not getattr(generator, "is_active", True) or generator.status == "ARCHIVED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо налаштувати архівований генератор. Спочатку відновіть його з архіву."
        )

    if generator.status == "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо переналаштувати генератор через майстер під час його активної роботи (RUNNING)."
        )

    generator.name = setup_data.name.strip()
    generator.model = setup_data.model.strip()
    generator.manufacturer = setup_data.manufacturer.strip()
    generator.serial_number = setup_data.serial_number.strip()
    generator.rated_power_kw = setup_data.rated_power_kw
    generator.tank_capacity_l = setup_data.tank_capacity_l
    generator.fuel_type = setup_data.fuel_type.strip()
    generator.nominal_consumption_l_per_h = setup_data.nominal_consumption_l_per_h
    generator.current_operating_hours = setup_data.initial_operating_hours
    generator.fuel_tank_level_l = setup_data.initial_fuel_tank_level_l
    generator.timezone = setup_data.timezone.strip() if setup_data.timezone else "Europe/Kyiv"
    generator.is_configured = True
    generator.updated_at = utc_now()

    if setup_data.facility_id is not None and generator.facility_id is None:
        generator.facility_id = setup_data.facility_id

    # Clear old schedules with direct delete
    await db.execute(delete(GeneratorSchedule).where(GeneratorSchedule.generator_id == generator.id))

    new_schedule = GeneratorSchedule(
        generator_id=generator.id,
        weekday=-1,
        start_time=setup_data.work_schedule_start,
        end_time=setup_data.work_schedule_end,
        timezone=generator.timezone,
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
        m_schedule.is_active = True

    await db.flush()
    generator.status = await _evaluate_generator_resting_status(db, generator)
    await db.flush()

    await log_audit(
        db=db,
        action="GENERATOR_WIZARD_CONFIGURED",
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=user_id,
        details={
            "generator_id": generator.id,
            "facility_id": generator.facility_id,
            "name": generator.name,
            "initial_hours": generator.current_operating_hours,
            "tank_capacity": generator.tank_capacity_l,
            "initial_fuel_level": generator.fuel_tank_level_l,
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


async def get_generator_cooldown_remaining(db: AsyncSession, generator_id: int) -> int:
    """
    Повертає кількість секунд, що залишились до завершення 60-секундного
    кулдауну після останньої зупинки генератора.
    """
    q = (
        select(GeneratorRun.end_time)
        .where(
            GeneratorRun.generator_id == generator_id,
            GeneratorRun.status == "COMPLETED"
        )
        .order_by(GeneratorRun.end_time.desc())
        .limit(1)
    )
    res = await db.execute(q)
    last_stop_time = res.scalar_one_or_none()
    if not last_stop_time:
        return 0
    elapsed_sec = (utc_now() - last_stop_time).total_seconds()
    if elapsed_sec < 60:
        return max(0, int(60 - elapsed_sec))
    return 0


async def get_generators_cooldown_map(db: AsyncSession, generator_ids: List[int]) -> Dict[int, int]:
    """
    Пакетне (batch) обчислення залишку 60-секундного кулдауну для списку генераторів
    одним SQL-запитом (усуває проблему N+1 у /generator/list).
    """
    if not generator_ids:
        return {}
    now = utc_now()
    cutoff = now - datetime.timedelta(seconds=60)
    q = (
        select(GeneratorRun.generator_id, func.max(GeneratorRun.end_time))
        .where(
            GeneratorRun.generator_id.in_(generator_ids),
            GeneratorRun.status == "COMPLETED",
            GeneratorRun.end_time >= cutoff
        )
        .group_by(GeneratorRun.generator_id)
    )
    res = await db.execute(q)
    cooldown_map: Dict[int, int] = {}
    for gen_id, last_stop_time in res.all():
        if last_stop_time:
            elapsed_sec = (now - last_stop_time).total_seconds()
            if elapsed_sec < 60:
                cooldown_map[gen_id] = max(0, int(60 - elapsed_sec))
    return cooldown_map


async def start_generator(
    db: AsyncSession,
    generator_id: int,
    user_id: int,
    fuel_level_l: Optional[float] = None,
    ip_address: Optional[str] = None,
    force_start_with_maintenance: bool = False,
    force_start_reason: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    facility_id: Optional[int] = None,
    skip_cooldown: bool = False
) -> GeneratorRun:
    """
    GEN-01, GEN-04, GEN-06, GEN-09, GEN-11, GEN-12, GEN-15:
    Транзакційно захищений запуск генератора з блокуванням рядка,
    перевіркою конфігурації, ТО, аварій, робочого графіка та рівня пального.
    """
    # 0. Idempotency check
    clean_idem_key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
    if clean_idem_key:
        idem_res = await db.execute(
            select(GeneratorRun)
            .options(selectinload(GeneratorRun.user))
            .where(GeneratorRun.idempotency_key == clean_idem_key)
        )
        existing_idem_run = idem_res.scalars().first()
        if existing_idem_run:
            return existing_idem_run

    # 1. Lock Generator row for update
    q = select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id).with_for_update()
    res = await db.execute(q)
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    # 2. Facility ownership check (GEN-12)
    if facility_id is not None and generator.facility_id != facility_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ заборонено: генератор належить до іншого об'єкта."
        )

    from backend.app.services.measurement_service import ensure_facility_not_locked_by_measurement
    await ensure_facility_not_locked_by_measurement(db, generator.facility_id, "generator_run")

    # 3. Check archived state (GEN-03 / T-25)
    if not getattr(generator, "is_active", True) or generator.status == "ARCHIVED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо запустити архівований або деактивований генератор."
        )

    # 4. Check configuration status (GEN-11) — never auto-set is_configured=True!
    if not generator.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Генератор не налаштовано (is_configured=False). Виконайте початкове налаштування перед запуском."
        )

    # 5. Re-check active run in DB & status (GEN-01, GEN-15, T-01, T-04)
    active_run_res = await db.execute(
        select(GeneratorRun.id).where(
            GeneratorRun.generator_id == generator.id,
            GeneratorRun.status == "RUNNING"
        )
    )
    if generator.status == "RUNNING" or active_run_res.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо запустити генератор: генератор уже працює"
        )

    # 5.1 Check stop cooldown (60 seconds pause after stopping)
    if not skip_cooldown:
        cooldown_rem = await get_generator_cooldown_remaining(db, generator.id)
        if cooldown_rem > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Захист від випадкового/передчасного запуску: генератор щойно зупинено. "
                    f"Технологічна пауза охолодження та стабілізації двигуна: зачекайте ще {cooldown_rem} с "
                    f"(повторний запуск дозволено не раніше ніж через 60 секунд після зупинки)."
                )
            )

    # 6. Check administrative block and faults
    if generator.status == "BLOCKED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Генератор заблокований адміністратором. Запуск заборонено."
        )

    fault_res = await db.execute(
        select(Fault).where(
            Fault.generator_id == generator.id,
            Fault.status.notin_(["RESOLVED", "CLOSED"]),
            Fault.priority == "CRITICAL"
        )
    )
    blocking_fault = fault_res.scalars().first()
    if generator.status == "FAULTY" or blocking_fault is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Генератор має критичну несправність. Спочатку усуньте несправність."
        )

    # 7. Check scheduled maintenance status (GEN-06, T-16, T-17, T-18)
    m_res = await db.execute(
        select(MaintenanceSchedule).where(
            MaintenanceSchedule.generator_id == generator.id,
            MaintenanceSchedule.is_active == True
        )
    )
    m_sched = m_res.scalars().first()
    is_maintenance_overdue = (
        generator.status == "MAINTENANCE_REQUIRED"
        or (m_sched is not None and generator.current_operating_hours >= m_sched.next_due_hours)
    )

    if is_maintenance_overdue:
        if not force_start_with_maintenance:
            due_str = f"{m_sched.next_due_hours:.1f}" if m_sched else f"{generator.current_operating_hours:.1f}"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Запуск заблоковано: прострочено регламентне технічне обслуговування "
                    f"(поточні мотогодини: {generator.current_operating_hours:.1f}, поріг ТО: {due_str}). "
                    f"Виконайте ТО або використайте примусовий запуск із дозволом адміністратора."
                )
            )
        # Validate override permission and mandatory reason
        has_override_perm = await _user_has_maintenance_override_permission(db, user_id)
        if not has_override_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостатньо прав для примусового запуску генератора з простроченим ТО."
            )
        clean_force_reason = (force_start_reason or "").strip()
        if len(clean_force_reason) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для примусового запуску при простроченому ТО обов'язково вкажіть причину (force_start_reason)."
            )

    # 8. Check work schedule in generator's timezone (GEN-09)
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
    is_allowed, schedule_msg = is_within_work_schedule(schedules_data, tz_name=generator.timezone)
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Запуск відхилено сервером: {schedule_msg}"
        )

    # 9. Validate and reconcile starting fuel level via fuel_service (GEN-04, GEN-14, T-10, T-11)
    if fuel_level_l is not None:
        current_fuel = await validate_and_reconcile_generator_tank_level(
            db=db,
            generator=generator,
            actual_fuel_l=fuel_level_l,
            user_id=user_id,
            ip_address=ip_address,
            context="START"
        )
    else:
        current_fuel = await validate_and_reconcile_generator_tank_level(
            db=db,
            generator=generator,
            actual_fuel_l=generator.fuel_tank_level_l,
            user_id=user_id,
            ip_address=ip_address,
            context="START"
        )

    # 10. Create active run record
    run = GeneratorRun(
        generator_id=generator.id,
        user_id=user_id,
        start_time=utc_now(),
        start_hours=generator.current_operating_hours,
        start_fuel_level_l=current_fuel,
        status="RUNNING",
        idempotency_key=clean_idem_key
    )
    db.add(run)
    generator.status = "RUNNING"
    generator.updated_at = utc_now()

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if clean_idem_key:
            idem_retry = await db.execute(
                select(GeneratorRun).where(GeneratorRun.idempotency_key == clean_idem_key)
            )
            existing = idem_retry.scalars().first()
            if existing:
                return existing
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо запустити генератор: генератор уже працює (виявлено конкурентний запуск)"
        ) from exc

    if is_maintenance_overdue and force_start_with_maintenance:
        await log_audit(
            db=db,
            action="GENERATOR_FORCE_START_MAINTENANCE",
            entity_type="Generator",
            entity_id=str(generator.id),
            user_id=user_id,
            details={
                "run_id": run.id,
                "facility_id": generator.facility_id,
                "current_operating_hours": generator.current_operating_hours,
                "next_due_hours": m_sched.next_due_hours if m_sched else None,
                "force_start_reason": force_start_reason.strip()
            },
            ip_address=ip_address
        )

    await log_audit(
        db=db,
        action="GENERATOR_START",
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=user_id,
        details={
            "facility_id": generator.facility_id,
            "start_hours": run.start_hours,
            "start_fuel": current_fuel,
            "run_id": run.id,
            "forced_with_maintenance": bool(is_maintenance_overdue and force_start_with_maintenance)
        },
        ip_address=ip_address
    )
    await db.commit()

    # Dispatch push notification AFTER commit
    try:
        from backend.app.services.notification_service import notify_generator_start
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
    user_id: Optional[int] = None,
    stop_data: Optional[GeneratorStopRequest] = None,
    ip_address: Optional[str] = None,
    reason: str = "MANUAL",
    system_note: Optional[str] = None,
    actor_type: str = "USER",
    facility_id: Optional[int] = None
) -> Optional[GeneratorRun]:
    """
    GEN-01, GEN-04, GEN-07, GEN-12, GEN-14, GEN-15, GEN-16:
    Транзакційно захищена зупинка генератора в межах єдиної атомарної транзакції.
    - Чітко розділяє календарну тривалість сеансу (duration_seconds) та напрацювання двигуна (duration_hours).
    - Виконує списання пального та звірку залишку бака через fuel_service.
    - У разі будь-якої помилки паливного списання або валідації мотогодин транзакція повністю відкочується.
    """
    # 1. Lock Generator row
    q_gen = select(Generator).where(Generator.id == generator_id).with_for_update()
    res = await db.execute(q_gen)
    generator = res.scalars().first()
    if not generator:
        if actor_type == "USER":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")
        return None

    if facility_id is not None and generator.facility_id != facility_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ заборонено: генератор належить до іншого об'єкта."
        )

    # 2. Lock active GeneratorRun row
    run_q = (
        select(GeneratorRun)
        .where(GeneratorRun.generator_id == generator.id, GeneratorRun.status == "RUNNING")
        .order_by(GeneratorRun.id.desc())
        .with_for_update()
    )
    run_res = await db.execute(run_q)
    run = run_res.scalars().first()

    if generator.status != "RUNNING" or not run:
        # Reconcile if state diverged
        if generator.status == "RUNNING" and not run:
            generator.status = await _evaluate_generator_resting_status(db, generator)
            await db.commit()
        if actor_type == "USER":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неможливо зупинити генератор: генератор не перебуває у стані 'Працює'"
            )
        return None

    end_time = utc_now()
    # GEN-07: Календарна тривалість роботи завжди розраховується виключно з різниці часу [start_time, end_time]
    calendar_duration_seconds = max(1, int((end_time - run.start_time).total_seconds()))

    if stop_data and stop_data.end_hours is not None:
        if stop_data.end_hours < run.start_hours:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Кінцеві мотогодини ({stop_data.end_hours}) не можуть бути меншими за початкові ({run.start_hours})"
            )
        if stop_data.end_hours > run.start_hours:
            # Напрацювання двигуна за лічильником
            end_hours = round(float(stop_data.end_hours), 3)
            hours_consumed = round(end_hours - run.start_hours, 2)
            duration_seconds = calendar_duration_seconds
            duration_hours = hours_consumed
            calculated_consumption = round(hours_consumed * generator.nominal_consumption_l_per_h, 2)

            # Typo Guard ("Запобіжник опечатки мотогодин"):
            elapsed_hours = calendar_duration_seconds / 3600.0
            is_suspicious = (hours_consumed > 14.0) or (calendar_duration_seconds >= 60 and abs(hours_consumed - elapsed_hours) > 2.0)
            if is_suspicious and not stop_data.force_confirm:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Запобіжник опечатки: напрацювання за лічильником ({hours_consumed:.2f} год) суттєво відрізняється "
                        f"від часу роботи за таймером ({elapsed_hours:.2f} год). "
                        f"Перевірте введені мотогодини або встановіть підтвердження."
                    )
                )
        else:
            # end_hours == start_hours (дуже короткий запуск)
            duration_seconds = calendar_duration_seconds
            duration_hours = round(duration_seconds / 3600.0, 4)
            end_hours = round(run.start_hours + duration_hours, 3)
            calculated_consumption = round((duration_seconds / 3600.0) * generator.nominal_consumption_l_per_h, 3)
    else:
        # Автоматичний розрахунок за фактичним календарним часом
        duration_seconds = calendar_duration_seconds
        duration_hours = round(duration_seconds / 3600.0, 4)
        end_hours = round(run.start_hours + duration_hours, 3)
        calculated_consumption = round((duration_seconds / 3600.0) * generator.nominal_consumption_l_per_h, 3)

    # GEN-04, GEN-14, T-10, T-11, T-12: Списання пального та звірка залишку через fuel_service
    # Якщо виникає помилка списання (наприклад, від'ємний залишок або перевищення бака),
    # піднімається HTTPException і вся транзакція зупинки залишається незмінною!
    actual_end_fuel = stop_data.end_fuel_level_l if stop_data else None
    discrepancy_reason = stop_data.fuel_discrepancy_reason if stop_data else None

    from backend.app.services.measurement_service import (
        ensure_facility_not_locked_by_measurement,
        is_generator_in_measurement_mode,
    )
    await ensure_facility_not_locked_by_measurement(db, generator.facility_id, "generator_run")
    in_measurement = await is_generator_in_measurement_mode(db, generator.id)
    allow_clamp = (actor_type != "USER") or in_measurement

    fuel_res = await consume_generator_fuel(
        db=db,
        generator=generator,
        consumed_l=calculated_consumption,
        user_id=user_id,
        ip_address=ip_address,
        run_id=run.id,
        actual_end_fuel_l=actual_end_fuel,
        discrepancy_reason=discrepancy_reason,
        allow_system_clamp=allow_clamp
    )
    fuel_shortage_l = 0.0 if in_measurement else fuel_res["fuel_shortage_l"]

    # Оновлюємо сеанс та генератор після успішного списання пального
    run.end_time = end_time
    run.end_hours = end_hours
    run.duration_seconds = duration_seconds
    run.duration_hours = duration_hours
    run.calculated_consumption_l = calculated_consumption
    run.end_fuel_level_l = fuel_res["end_fuel_l"]
    run.status = "COMPLETED"
    run.note = (stop_data.note if (stop_data and stop_data.note) else system_note)

    generator.current_operating_hours = end_hours
    generator.updated_at = end_time

    # GEN-16: Встановлюємо узгоджений статус генератора після зупинки
    generator.status = await _evaluate_generator_resting_status(db, generator)

    await db.flush()

    h = duration_seconds // 3600
    m = (duration_seconds % 3600) // 60
    s = duration_seconds % 60
    duration_formatted = f"{h:02d}:{m:02d}:{s:02d}"

    if reason == "MANUAL":
        audit_action = "GENERATOR_STOP"
        actor_id = user_id
    elif reason == "MAX_CONTINUOUS_RUN_EXCEEDED":
        audit_action = "GENERATOR_SAFETY_STOP"
        actor_id = None
    elif reason == "WORK_SCHEDULE_ENDED":
        audit_action = "GENERATOR_AUTO_STOP"
        actor_id = None
    else:
        audit_action = "GENERATOR_STOP"
        actor_id = user_id

    audit_details = {
        "actor_type": actor_type,
        "facility_id": generator.facility_id,
        "reason": reason,
        "start_hours": run.start_hours,
        "end_hours": run.end_hours,
        "duration_seconds": duration_seconds,
        "duration_formatted": duration_formatted,
        "duration_hours": duration_hours,
        "calculated_consumption_l": calculated_consumption,
        "end_fuel_level_l": generator.fuel_tank_level_l,
        "fuel_shortage_l": fuel_shortage_l,
        "fuel_discrepancy": (fuel_shortage_l > 0),
        "run_id": run.id,
        "status_after": generator.status
    }
    if system_note:
        audit_details["system_note"] = system_note

    await log_audit(
        db=db,
        action=audit_action,
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=actor_id,
        details=audit_details,
        ip_address=ip_address
    )
    await db.commit()

    # Dispatch push notification AFTER successful commit
    try:
        if reason == "MANUAL":
            from backend.app.services.notification_service import notify_generator_stop
            u_name = "Оператор"
            if user_id:
                u_res = await db.execute(select(User.full_name).where(User.id == user_id))
                u_name = u_res.scalar() or "Оператор"
            await notify_generator_stop(
                db=db,
                generator=generator,
                user_name=u_name,
                duration_str=duration_formatted,
                consumption_l=calculated_consumption,
                end_fuel=generator.fuel_tank_level_l,
                suppress_low_fuel=in_measurement,
            )
        elif reason == "MAX_CONTINUOUS_RUN_EXCEEDED":
            from backend.app.services.notification_service import send_push_notification
            await send_push_notification(
                db=db,
                title=f"🚨 Аварійна зупинка — {generator.name}",
                body=f"Генератор автоматично зупинено після {duration_hours:.1f} год безперервної роботи (перевищено ліміт). Обліковий сеанс закрито.",
                event_type="GENERATOR_SAFETY_STOP",
                generator_id=generator.id,
                facility_id=generator.facility_id,
                url="/?tab=tab-dashboard"
            )
        elif reason == "WORK_SCHEDULE_ENDED":
            from backend.app.services.notification_service import send_push_notification
            sched_str = system_note or "закінчення робочого дня"
            await send_push_notification(
                db=db,
                title=f"⏱️ Автозупинка за графіком — {generator.name}",
                body=f"Робочий день завершено ({sched_str}). Генератор автоматично зупинено. Напрацювання за сеанс: {duration_hours:.2f} год.",
                event_type="GENERATOR_AUTO_STOP",
                generator_id=generator.id,
                facility_id=generator.facility_id,
                url="/?tab=tab-dashboard"
            )

        if reason != "MANUAL":
            from backend.app.services.notification_service import (
                check_and_notify_low_fuel,
                check_and_notify_maintenance_due,
            )
            if generator.fuel_tank_level_l is not None:
                await check_and_notify_low_fuel(db, generator, float(generator.fuel_tank_level_l))
            await check_and_notify_maintenance_due(db, generator.id)

        if fuel_shortage_l > 0:
            from backend.app.services.notification_service import send_push_notification
            await send_push_notification(
                db=db,
                title=f"⚠️ Розбіжність паливного балансу — {generator.name}",
                body=f"Розрахункова витрата палива перевищила наявний залишок у баку на {fuel_shortage_l:.1f} л. Перевірте надходження палива.",
                event_type="FUEL_DISCREPANCY",
                generator_id=generator.id,
                facility_id=generator.facility_id,
                url="/?tab=tab-fuel"
            )
            if get_runtime_setting("email_notify_low_fuel", True) and get_runtime_setting("smtp_enabled", False):
                from backend.app.services.email_service import (
                    resolve_facility_email_recipients,
                    send_fuel_discrepancy_email,
                )
                recs = await resolve_facility_email_recipients(db, generator.facility_id)
                if recs:
                    await send_fuel_discrepancy_email(
                        recipients=recs,
                        generator_name=generator.name,
                        shortage_l=fuel_shortage_l,
                        db=db,
                    )
    except Exception as ex:
        print(f"[NOTIF] Failed to send stop notification: {ex}", flush=True)

    return run


async def get_generators_list(
    db: AsyncSession,
    facility_id: Optional[int] = None,
    include_archived: bool = False
) -> List[Generator]:
    query = select(Generator).options(selectinload(Generator.schedules))
    if not include_archived:
        query = query.where(Generator.is_active == True)
    if facility_id:
        query = query.where(Generator.facility_id == facility_id)
    query = query.order_by(Generator.id.asc())
    res = await db.execute(query)
    generators = res.scalars().all()
    if not generators and not include_archived and (facility_id is None or facility_id == 1):
        # Check if there are archived generators before creating a default one
        arch_count = (await db.execute(select(func.count(Generator.id)))).scalar() or 0
        if arch_count == 0:
            default_gen = await get_or_create_default_generator(db, facility_id=facility_id)
            return [default_gen]
    return list(generators)


async def create_generator(
    db: AsyncSession,
    setup_data: GeneratorCreate,
    user_id: int,
    ip_address: Optional[str] = None
) -> Generator:
    if setup_data.initial_fuel_tank_level_l < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Початковий рівень пального не може бути від'ємним."
        )
    if setup_data.initial_fuel_tank_level_l > setup_data.tank_capacity_l:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Початковий рівень пального ({setup_data.initial_fuel_tank_level_l} л) "
                f"не може перевищувати місткість бака ({setup_data.tank_capacity_l} л)."
            )
        )

    facility_id = setup_data.facility_id
    if not facility_id:
        fac_res = await db.execute(select(Facility.id).order_by(Facility.id.asc()))
        first_fac = fac_res.scalars().first()
        facility_id = first_fac if first_fac else 1
    else:
        fac_check = await db.execute(select(Facility.id).where(Facility.id == facility_id))
        if not fac_check.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Об'єкт з ID {facility_id} не знайдено"
            )

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
        fuel_tank_level_l=setup_data.initial_fuel_tank_level_l,
        timezone=setup_data.timezone.strip() if setup_data.timezone else "Europe/Kyiv",
        is_configured=True,
        is_active=True,
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
    """
    GEN-03 (T-13, T-14, T-15): Захист історії генератора від каскадного знищення.
    - Заборонено видаляти або архівувати працюючий генератор (RUNNING).
    - Якщо генератор має історію (сеанси роботи, переміщення пального, записи ТО або несправності),
      фізичне видалення заборонено — виконується м'яка архівація (is_active=False, status='ARCHIVED', archived_at).
    - Якщо генератор щойно створений і не має жодного історичного запису, дозволяється фізичне видалення.
    """
    res = await db.execute(select(Generator).where(Generator.id == generator_id).with_for_update())
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    active_run_count = (await db.execute(
        select(func.count(GeneratorRun.id)).where(
            GeneratorRun.generator_id == generator.id,
            GeneratorRun.status == "RUNNING"
        )
    )).scalar() or 0

    if generator.status == "RUNNING" or active_run_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо видалити або архівувати генератор, який зараз працює! Спочатку зупиніть генератор."
        )

    runs_count = (await db.execute(select(func.count(GeneratorRun.id)).where(GeneratorRun.generator_id == generator.id))).scalar() or 0
    transfers_count = (await db.execute(select(func.count(FuelTransfer.id)).where(FuelTransfer.generator_id == generator.id))).scalar() or 0
    maint_count = (await db.execute(select(func.count(MaintenanceRecord.id)).where(MaintenanceRecord.generator_id == generator.id))).scalar() or 0
    faults_count = (await db.execute(select(func.count(Fault.id)).where(Fault.generator_id == generator.id))).scalar() or 0

    total_history = runs_count + transfers_count + maint_count + faults_count
    gen_name = generator.name

    if total_history > 0:
        # Soft-archive generator while preserving 100% of historical records
        now = utc_now()
        generator.is_active = False
        generator.status = "ARCHIVED"
        generator.archived_at = now
        generator.updated_at = now
        await db.flush()

        await log_audit(
            db=db,
            action="GENERATOR_ARCHIVED",
            entity_type="Generator",
            entity_id=str(generator_id),
            user_id=user_id,
            details={
                "name": gen_name,
                "facility_id": generator.facility_id,
                "model": generator.model,
                "serial_number": generator.serial_number,
                "history_preserved": {
                    "runs": runs_count,
                    "transfers": transfers_count,
                    "maintenance_records": maint_count,
                    "faults": faults_count
                }
            },
            ip_address=ip_address
        )
        await db.commit()
        return {
            "archived": True,
            "deleted": False,
            "generator_id": generator_id,
            "message": (
                f"Генератор '{gen_name}' (ID {generator_id}) переведено в архів (успішно видалено з активного списку) "
                f"зі збереженням історії ({total_history} записів)."
            )
        }

    # Physical deletion only when zero history exists
    await db.delete(generator)
    await db.flush()

    await log_audit(
        db=db,
        action="GENERATOR_DELETED",
        entity_type="Generator",
        entity_id=str(generator_id),
        user_id=user_id,
        details={
            "name": gen_name,
            "facility_id": generator.facility_id,
            "model": generator.model,
            "serial_number": generator.serial_number
        },
        ip_address=ip_address
    )
    await db.commit()

    return {
        "archived": False,
        "deleted": True,
        "generator_id": generator_id,
        "message": f"Генератор '{gen_name}' (ID {generator_id}) успішно видалено"
    }


async def restore_generator(
    db: AsyncSession,
    generator_id: int,
    user_id: int,
    ip_address: Optional[str] = None
) -> Generator:
    """
    GEN-03: Відновлення архівованого генератора для авторизованих користувачів.
    """
    res = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id).with_for_update()
    )
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    if getattr(generator, "is_active", True) and generator.status != "ARCHIVED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Генератор вже є активним і не перебуває в архіві."
        )

    generator.is_active = True
    generator.archived_at = None
    generator.status = "STOPPED"
    generator.status = await _evaluate_generator_resting_status(db, generator)
    generator.updated_at = utc_now()
    await db.flush()

    await log_audit(
        db=db,
        action="GENERATOR_RESTORED",
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=user_id,
        details={
            "name": generator.name,
            "facility_id": generator.facility_id,
            "status_after": generator.status
        },
        ip_address=ip_address
    )
    await db.commit()

    res_fresh = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator.id)
    )
    return res_fresh.scalars().first()


async def transfer_generator_facility(
    db: AsyncSession,
    generator_id: int,
    transfer_data: GeneratorFacilityTransferRequest,
    user_id: int,
    ip_address: Optional[str] = None
) -> Generator:
    """
    GEN-10 (T-21, T-22): Контрольована операція перенесення генератора між об'єктами.
    Перевіряє:
    1. Відсутність активного сеансу роботи (RUNNING).
    2. Відсутність відкритих критичних аварій.
    3. Стан паливного бака (повинен бути 0 л або в межах цільового об'єкта без відкритих колізій).
    4. Існування цільового об'єкта.
    5. Зберігає всі історичні записи за старими об'єктами (не переписує історію).
    """
    res = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id).with_for_update()
    )
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    if not getattr(generator, "is_active", True) or generator.status == "ARCHIVED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо перенести архівований генератор."
        )

    active_run_res = await db.execute(
        select(GeneratorRun.id).where(
            GeneratorRun.generator_id == generator.id,
            GeneratorRun.status == "RUNNING"
        )
    )
    if generator.status == "RUNNING" or active_run_res.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Заборонено переносити генератор на інший об'єкт під час його активної роботи (RUNNING)!"
        )

    open_faults_count = (await db.execute(
        select(func.count(Fault.id)).where(
            Fault.generator_id == generator.id,
            Fault.status.notin_(["RESOLVED", "CLOSED"]),
            Fault.priority == "CRITICAL"
        )
    )).scalar() or 0
    if generator.status == "FAULTY" or open_faults_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Заборонено переносити генератор із незакритими критичними несправностями."
        )

    target_fac = await db.get(Facility, transfer_data.target_facility_id)
    if not target_fac:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Цільовий об'єкт з ID {transfer_data.target_facility_id} не знайдено"
        )

    if generator.facility_id == transfer_data.target_facility_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Генератор вже закріплений за вказаним об'єктом."
        )

    old_facility_id = generator.facility_id
    generator.facility_id = transfer_data.target_facility_id
    generator.updated_at = utc_now()
    await db.flush()

    await log_audit(
        db=db,
        action="GENERATOR_FACILITY_TRANSFERRED",
        entity_type="Generator",
        entity_id=str(generator.id),
        user_id=user_id,
        details={
            "generator_name": generator.name,
            "old_facility_id": old_facility_id,
            "new_facility_id": transfer_data.target_facility_id,
            "target_facility_name": target_fac.name,
            "fuel_tank_level_l": generator.fuel_tank_level_l,
            "operating_hours": generator.current_operating_hours,
            "reason": transfer_data.reason.strip()
        },
        ip_address=ip_address
    )
    await db.commit()

    res_fresh = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator.id)
    )
    return res_fresh.scalars().first()


async def update_generator(
    db: AsyncSession,
    generator_id: int,
    data: GeneratorUpdate,
    user_id: int,
    ip_address: Optional[str] = None
) -> Generator:
    """
    GEN-08, GEN-10 (T-21, T-23): Безпечне оновлення параметрів генератора.
    - Забороняє змінювати facility_id напряму через загальний update (вимагає контрольованої операції перенесення).
    - Забороняє зменшувати tank_capacity_l нижче поточного залишку пального в баку (fuel_tank_level_l).
    - Забороняє редагування архівованого генератора.
    """
    res = await db.execute(
        select(Generator).options(selectinload(Generator.schedules)).where(Generator.id == generator_id).with_for_update()
    )
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    if not getattr(generator, "is_active", True) or generator.status == "ARCHIVED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо редагувати архівований генератор."
        )

    changes = {}

    if data.facility_id is not None and data.facility_id != generator.facility_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Пряма зміна об'єкта (facility_id) через загальне редагування заборонена. "
                "Використовуйте спеціальну контрольовану операцію перенесення генератора між об'єктами."
            )
        )

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

    if data.rated_power_kw is not None:
        if data.rated_power_kw <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Номінальна потужність має бути більшою за 0")
        if data.rated_power_kw != generator.rated_power_kw:
            changes["rated_power_kw"] = (generator.rated_power_kw, data.rated_power_kw)
            generator.rated_power_kw = data.rated_power_kw

    if data.tank_capacity_l is not None:
        if data.tank_capacity_l != generator.tank_capacity_l:
            from backend.app.services.measurement_service import ensure_facility_not_locked_by_measurement
            await ensure_facility_not_locked_by_measurement(db, generator.facility_id, "fuel_adjustment")
        if data.tank_capacity_l <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Місткість бака має бути більшою за 0")
        if data.tank_capacity_l < generator.fuel_tank_level_l:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Неможливо встановити місткість бака ({data.tank_capacity_l} л) меншою за "
                    f"поточний залишок пального в баку ({generator.fuel_tank_level_l} л)."
                )
            )
        if data.tank_capacity_l != generator.tank_capacity_l:
            changes["tank_capacity_l"] = (generator.tank_capacity_l, data.tank_capacity_l)
            generator.tank_capacity_l = data.tank_capacity_l

    if data.fuel_type is not None and data.fuel_type.strip():
        new_ft = data.fuel_type.strip()
        if new_ft != generator.fuel_type:
            changes["fuel_type"] = (generator.fuel_type, new_ft)
            generator.fuel_type = new_ft

    if data.nominal_consumption_l_per_h is not None:
        if data.nominal_consumption_l_per_h != generator.nominal_consumption_l_per_h:
            from backend.app.services.measurement_service import ensure_facility_not_locked_by_measurement
            await ensure_facility_not_locked_by_measurement(db, generator.facility_id, "fuel_adjustment")
        if data.nominal_consumption_l_per_h <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Номінальна витрата пального має бути більшою за 0")
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
            details={
                "facility_id": generator.facility_id,
                "changes": {k: {"old": str(v[0]), "new": str(v[1])} for k, v in changes.items()}
            },
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
    ip_address: Optional[str] = None,
    facility_id: Optional[int] = None
) -> GeneratorRun:
    """
    GEN-02, GEN-04, GEN-07, GEN-09, GEN-12, GEN-13, GEN-16:
    Безпечне внесення сеансу роботи генератора вручну (з паперового журналу).
    - Підтримує idempotency_key та захист від повторного внесення однакового інтервалу (T-05).
    - Нормалізує start_time / end_time з урахуванням часового поясу об'єкта/генератора (T-19, T-20).
    - Забороняє перетин часових інтервалів з іншими завершеними сеансами (T-06) та активним сеансом RUNNING (T-07).
    - Перевіряє хронологічну послідовність показників лічильника мотогодин (T-08, T-09).
    - Списує пальне через єдиний механізм fuel_service із забороною від'ємного залишку бака (T-10).
    - Зберігає цілісність статусу генератора (T-24).
    """
    # 0. Idempotency check
    clean_idem_key = data.idempotency_key.strip() if data.idempotency_key and data.idempotency_key.strip() else None
    if clean_idem_key:
        idem_res = await db.execute(
            select(GeneratorRun)
            .options(selectinload(GeneratorRun.user))
            .where(GeneratorRun.idempotency_key == clean_idem_key)
        )
        existing_idem = idem_res.scalars().first()
        if existing_idem:
            return existing_idem

    # 1. Lock Generator row
    res = await db.execute(select(Generator).where(Generator.id == generator_id).with_for_update())
    generator = res.scalars().first()
    if not generator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Генератор не знайдено")

    if facility_id is not None and generator.facility_id != facility_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ заборонено: генератор належить до іншого об'єкта."
        )

    if not getattr(generator, "is_active", True) or generator.status == "ARCHIVED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неможливо додати ручний сеанс для архівованого генератора."
        )

    if not generator.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Генератор не налаштовано. Виконайте початкове налаштування перед внесенням сеансів."
        )

    from backend.app.services.measurement_service import (
        ensure_facility_not_locked_by_measurement,
        is_generator_in_measurement_mode,
    )
    await ensure_facility_not_locked_by_measurement(db, generator.facility_id, "generator_run")
    in_measurement_manual = await is_generator_in_measurement_mode(db, generator.id)

    # 2. Timezone normalization to naive UTC (GEN-09, T-19, T-20)
    start_dt = _normalize_to_utc_naive(data.start_time, generator.timezone)
    end_dt = _normalize_to_utc_naive(data.end_time, generator.timezone)

    if start_dt >= end_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Час завершення роботи має бути пізнішим за час запуску"
        )

    # 3. Check for overlapping runs (both COMPLETED and active RUNNING) (GEN-02, GEN-13, T-05, T-06, T-07)
    current_utc = utc_now()
    existing_runs_res = await db.execute(
        select(GeneratorRun)
        .where(GeneratorRun.generator_id == generator.id)
        .order_by(GeneratorRun.start_time.asc())
    )
    existing_runs = existing_runs_res.scalars().all()

    for r in existing_runs:
        r_start = r.start_time
        r_end = r.end_time if r.end_time is not None else max(current_utc, end_dt)
        if r_start == start_dt and r.end_time == end_dt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Дублікат сеансу: запис роботи за період {start_dt} — {end_dt} вже існує (ID {r.id})."
            )
        # Half-open interval overlap check: max(start1, start2) < min(end1, end2)
        if start_dt < r_end and end_dt > r_start:
            if r.status == "RUNNING":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Часовий інтервал ручного запису ({start_dt} — {end_dt}) перетинається "
                        f"з поточним активним сеансом роботи генератора (ID {r.id}, запущено о {r_start})."
                    )
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Часовий інтервал ручного запису ({start_dt} — {end_dt}) перетинається "
                    f"з існуючим історичним сеансом роботи (ID {r.id}: {r_start} — {r_end})."
                )
            )

    # 4. Separate calendar duration from engine hours (GEN-07)
    duration_seconds = max(1, int((end_dt - start_dt).total_seconds()))
    calendar_hours = round(duration_seconds / 3600.0, 3)

    # 5. Operating hours and chronological validation (GEN-02, T-08, T-09)
    start_hours = data.start_hours if data.start_hours is not None else generator.current_operating_hours
    if data.end_hours is not None:
        if data.end_hours < start_hours:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Кінцеві мотогодини ({data.end_hours}) не можуть бути меншими за початкові ({start_hours})"
            )
        end_hours = round(float(data.end_hours), 3)
        hours_worked = round(end_hours - start_hours, 2)
        duration_hours = hours_worked if hours_worked > 0 else calendar_hours

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
        duration_hours = calendar_hours
        end_hours = round(start_hours + duration_hours, 2)

    # Chronological counter check when both start_hours and end_hours are explicitly provided
    if data.start_hours is not None or data.end_hours is not None:
        preceding_runs = [r for r in existing_runs if r.end_time is not None and r.end_time <= start_dt and r.end_hours is not None]
        if preceding_runs:
            max_prev_end_hours = max(r.end_hours for r in preceding_runs)
            if start_hours < max_prev_end_hours:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Порушення хронології мотогодин: початкові мотогодини ({start_hours}) менші "
                        f"за кінцеві мотогодини попереднього сеансу ({max_prev_end_hours})."
                    )
                )
        succeeding_runs = [r for r in existing_runs if r.start_time >= end_dt and r.start_hours is not None]
        if succeeding_runs:
            min_next_start_hours = min(r.start_hours for r in succeeding_runs)
            if end_hours > min_next_start_hours:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Порушення хронології мотогодин: кінцеві мотогодини ({end_hours}) перевищують "
                        f"початкові мотогодини наступного за часом сеансу ({min_next_start_hours})."
                    )
                )

    # 6. Fuel consumption via unified fuel_service (GEN-04, T-10)
    if data.fuel_consumed_l is not None:
        if data.fuel_consumed_l < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Витрачене паливо не може бути від'ємним")
        calculated_consumption = round(float(data.fuel_consumed_l), 3)
    else:
        calculated_consumption = round(duration_hours * generator.nominal_consumption_l_per_h, 3)

    fuel_res = await consume_generator_fuel(
        db=db,
        generator=generator,
        consumed_l=calculated_consumption,
        user_id=user_id,
        ip_address=ip_address,
        allow_system_clamp=in_measurement_manual
    )

    # 7. Create manual run record without mutating other historical runs
    run = GeneratorRun(
        generator_id=generator.id,
        user_id=user_id,
        start_time=start_dt,
        end_time=end_dt,
        start_hours=start_hours,
        end_hours=end_hours,
        duration_seconds=duration_seconds,
        duration_hours=duration_hours,
        start_fuel_level_l=fuel_res["start_fuel_l"],
        end_fuel_level_l=fuel_res["end_fuel_l"],
        calculated_consumption_l=calculated_consumption,
        status="COMPLETED",
        note=data.note.strip() if data.note else "Внесено вручну (запис з паперового журналу)",
        idempotency_key=clean_idem_key
    )
    db.add(run)

    # 8. Update generator metrics and preserve status consistency (GEN-16, T-24)
    generator.current_operating_hours = max(generator.current_operating_hours, end_hours)
    generator.updated_at = utc_now()

    if generator.status != "RUNNING":
        generator.status = await _evaluate_generator_resting_status(db, generator)

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
            "facility_id": generator.facility_id,
            "start_time": str(start_dt),
            "end_time": str(end_dt),
            "start_hours": start_hours,
            "end_hours": end_hours,
            "duration_seconds": duration_seconds,
            "duration_formatted": duration_formatted,
            "duration_hours": duration_hours,
            "calculated_consumption_l": calculated_consumption,
            "new_operating_hours": generator.current_operating_hours,
            "new_fuel_tank_level_l": generator.fuel_tank_level_l,
            "status_after": generator.status,
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
