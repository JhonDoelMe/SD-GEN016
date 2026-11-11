from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.schemas.generator import (
    GeneratorOut, GeneratorWizardSetup, GeneratorCreate, GeneratorStartRequest,
    GeneratorStopRequest, GeneratorRunOut, GeneratorUpdate, GeneratorManualRunCreate,
    GeneratorFacilityTransferRequest
)
from backend.app.api.deps import (
    get_current_user,
    require_permission,
    get_client_ip,
    is_user_admin_or_super,
    verify_facility_access,
    verify_generator_facility_access,
)
from backend.app.services.generator_service import (
    get_or_create_default_generator, setup_generator_wizard,
    start_generator, stop_generator, get_generators_list,
    create_generator, delete_generator, update_generator, add_manual_run,
    restore_generator, transfer_generator_facility, reconcile_generator_state,
    get_generator_cooldown_remaining, get_generators_cooldown_map
)
from backend.app.services.idempotency_service import resolve_idempotency_key, run_idempotent_endpoint


def format_seconds(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def run_to_out(run: GeneratorRun, user_name: Optional[str] = None) -> GeneratorRunOut:
    dur_sec = run.duration_seconds
    if dur_sec is None and run.start_time and run.end_time:
        dur_sec = max(0, int((run.end_time - run.start_time).total_seconds()))

    return GeneratorRunOut(
        id=run.id,
        generator_id=run.generator_id,
        user_id=run.user_id,
        user_name=user_name or ((run.user.full_name or run.user.login) if run.user else None),
        start_time=run.start_time,
        end_time=run.end_time,
        start_hours=run.start_hours,
        end_hours=run.end_hours,
        duration_hours=run.duration_hours,
        duration_seconds=dur_sec,
        duration_formatted=format_seconds(dur_sec),
        start_fuel_level_l=run.start_fuel_level_l,
        end_fuel_level_l=run.end_fuel_level_l,
        calculated_consumption_l=run.calculated_consumption_l,
        status=run.status,
        note=run.note
    )


router = APIRouter(prefix="/generator", tags=["Генератор"])


@router.get("", response_model=GeneratorOut)
async def get_generator(
    generator_id: Optional[int] = None,
    facility_id: Optional[int] = None,
    include_archived: bool = Query(False, description="Включити архівовані генератори"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    eff_facility_id = verify_facility_access(current_user, facility_id)
    await verify_generator_facility_access(db, current_user, generator_id)
    gen = await get_or_create_default_generator(
        db,
        generator_id=generator_id,
        facility_id=eff_facility_id,
        include_archived=include_archived
    )
    out = GeneratorOut.model_validate(gen)
    out.cooldown_remaining_seconds = (
        0 if gen.status == "RUNNING" else await get_generator_cooldown_remaining(db, gen.id)
    )
    return out


@router.get("/list", response_model=List[GeneratorOut])
async def list_all_generators(
    facility_id: Optional[int] = None,
    include_archived: bool = Query(False, description="Включити архівовані генератори"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Список усіх генераторів (з можливістю фільтрації за об'єкти)"""
    eff_facility_id = verify_facility_access(current_user, facility_id)
    gens = await get_generators_list(db, facility_id=eff_facility_id, include_archived=include_archived)
    stopped_ids = [g.id for g in gens if g.status != "RUNNING"]
    cooldown_map = await get_generators_cooldown_map(db, stopped_ids) if stopped_ids else {}
    res = []
    for g in gens:
        item = GeneratorOut.model_validate(g)
        item.cooldown_remaining_seconds = cooldown_map.get(g.id, 0)
        res.append(item)
    return res


@router.post("", response_model=GeneratorOut, status_code=status.HTTP_201_CREATED)
async def create_new_generator_api(
    data: GeneratorCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
    """Створити новий генератор"""
    verify_facility_access(current_user, data.facility_id)
    client_ip = get_client_ip(request)
    return await create_generator(db, data, current_user.id, client_ip)


@router.delete("/{generator_id}")
async def delete_generator_api(
    generator_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
    """Видалити або архівувати генератор"""
    await verify_generator_facility_access(db, current_user, generator_id)
    client_ip = get_client_ip(request)
    return await delete_generator(db, generator_id, current_user.id, client_ip)


@router.post("/{generator_id}/restore", response_model=GeneratorOut)
async def restore_generator_api(
    generator_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
    """Відновити архівований генератор"""
    await verify_generator_facility_access(db, current_user, generator_id)
    client_ip = get_client_ip(request)
    return await restore_generator(db, generator_id, current_user.id, client_ip)


@router.post("/{generator_id}/transfer-facility", response_model=GeneratorOut)
async def transfer_generator_facility_api(
    generator_id: int,
    data: GeneratorFacilityTransferRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
    """Контрольоване перенесення генератора на інший об'єкт"""
    await verify_generator_facility_access(db, current_user, generator_id)
    verify_facility_access(current_user, data.target_facility_id)
    client_ip = get_client_ip(request)
    return await transfer_generator_facility(db, generator_id, data, current_user.id, client_ip)


@router.post("/{generator_id}/reconcile", response_model=GeneratorOut)
async def reconcile_generator_api(
    generator_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
    """Діагностика та відновлення узгодженого статусу генератора"""
    await verify_generator_facility_access(db, current_user, generator_id)
    gen = await reconcile_generator_state(db, generator_id)
    await db.commit()
    return gen


@router.put("/{generator_id}", response_model=GeneratorOut)
async def update_generator_api(
    generator_id: int,
    data: GeneratorUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
    """Швидке оновлення налаштувань генератора (назва, модель, бак, розхід тощо)"""
    await verify_generator_facility_access(db, current_user, generator_id)
    if data.facility_id is not None:
        verify_facility_access(current_user, data.facility_id)
    client_ip = get_client_ip(request)
    return await update_generator(db, generator_id, data, current_user.id, client_ip)


@router.post("/wizard", response_model=GeneratorOut)
async def setup_wizard(
    setup_data: GeneratorWizardSetup,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
    if setup_data.generator_id is not None:
        await verify_generator_facility_access(db, current_user, setup_data.generator_id)
    if setup_data.facility_id is not None:
        verify_facility_access(current_user, setup_data.facility_id)
    elif not is_user_admin_or_super(current_user) and current_user.facility_id:
        setup_data.facility_id = current_user.facility_id
    gen = await setup_generator_wizard(
        db=db,
        setup_data=setup_data,
        user_id=current_user.id,
        ip_address=get_client_ip(request)
    )
    return gen


@router.post("/start", response_model=GeneratorRunOut)
async def api_start_generator(
    data: GeneratorStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:start"))
):
    await verify_generator_facility_access(db, current_user, data.generator_id)
    eff_fac_id = None if is_user_admin_or_super(current_user) else current_user.facility_id
    gen = await get_or_create_default_generator(
        db,
        generator_id=data.generator_id,
        facility_id=eff_fac_id,
        include_archived=True
    )
    idem_key = resolve_idempotency_key(request, data.idempotency_key)
    run = await start_generator(
        db=db,
        generator_id=gen.id,
        user_id=current_user.id,
        fuel_level_l=data.fuel_level_l,
        ip_address=get_client_ip(request),
        force_start_with_maintenance=data.force_start_with_maintenance,
        force_start_reason=data.force_start_reason,
        idempotency_key=idem_key,
        facility_id=eff_fac_id,
        skip_cooldown=getattr(data, "skip_cooldown", False)
    )
    return run_to_out(run, user_name=current_user.full_name)


@router.post("/stop", response_model=GeneratorRunOut)
async def api_stop_generator(
    data: GeneratorStopRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:stop"))
):
    await verify_generator_facility_access(db, current_user, data.generator_id)
    eff_fac_id = None if is_user_admin_or_super(current_user) else current_user.facility_id

    async def _exec():
        gen = await get_or_create_default_generator(
            db,
            generator_id=data.generator_id,
            facility_id=eff_fac_id,
            include_archived=True
        )
        run = await stop_generator(
            db=db,
            generator_id=gen.id,
            user_id=current_user.id,
            stop_data=data,
            ip_address=get_client_ip(request),
            facility_id=eff_fac_id
        )
        return run_to_out(run, user_name=current_user.full_name)

    return await run_idempotent_endpoint(
        db=db,
        request=request,
        current_user=current_user,
        endpoint="/generator/stop",
        body_data=data,
        success_status=status.HTTP_200_OK,
        action_fn=_exec,
    )


@router.post("/manual-run", response_model=GeneratorRunOut, status_code=status.HTTP_201_CREATED)
async def api_add_manual_run(
    data: GeneratorManualRunCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:start"))
):
    """Внесення сеансу роботи генератора вручну (з паперового журналу при відсутності зв'язку)"""
    await verify_generator_facility_access(db, current_user, data.generator_id)
    eff_fac_id = None if is_user_admin_or_super(current_user) else current_user.facility_id
    gen = await get_or_create_default_generator(
        db,
        generator_id=data.generator_id,
        facility_id=eff_fac_id,
        include_archived=True
    )
    data.idempotency_key = resolve_idempotency_key(request, data.idempotency_key)
    run = await add_manual_run(
        db=db,
        generator_id=gen.id,
        user_id=current_user.id,
        data=data,
        ip_address=get_client_ip(request),
        facility_id=eff_fac_id
    )
    return run_to_out(run, user_name=current_user.full_name)


@router.get("/active-run", response_model=Optional[GeneratorRunOut])
async def get_active_run(
    generator_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    await verify_generator_facility_access(db, current_user, generator_id)
    query = select(GeneratorRun).options(selectinload(GeneratorRun.user)).where(GeneratorRun.status == "RUNNING")
    if generator_id:
        query = query.where(GeneratorRun.generator_id == generator_id)
    elif not is_user_admin_or_super(current_user) and current_user.facility_id:
        query = query.join(Generator, GeneratorRun.generator_id == Generator.id).where(
            Generator.facility_id == current_user.facility_id
        )
    query = query.order_by(GeneratorRun.id.desc())
    res = await db.execute(query)
    run = res.scalars().first()
    if not run:
        return None
    return run_to_out(run)


@router.get("/runs", response_model=List[GeneratorRunOut])
async def list_runs(
    generator_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    await verify_generator_facility_access(db, current_user, generator_id)
    query = select(GeneratorRun).options(selectinload(GeneratorRun.user))
    if generator_id:
        query = query.where(GeneratorRun.generator_id == generator_id)
    elif not is_user_admin_or_super(current_user) and current_user.facility_id:
        query = query.join(Generator, GeneratorRun.generator_id == Generator.id).where(
            Generator.facility_id == current_user.facility_id
        )
    query = query.order_by(GeneratorRun.id.desc()).limit(limit)
    res = await db.execute(query)
    runs = res.scalars().all()
    return [run_to_out(r) for r in runs]
