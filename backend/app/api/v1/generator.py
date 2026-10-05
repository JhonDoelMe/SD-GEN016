from typing import List, Optional
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.schemas.generator import (
    GeneratorOut, GeneratorWizardSetup, GeneratorCreate, GeneratorStartRequest,
    GeneratorStopRequest, GeneratorRunOut
)
from backend.app.api.deps import get_current_user, require_permission, get_client_ip
from backend.app.services.generator_service import (
    get_or_create_default_generator, setup_generator_wizard,
    start_generator, stop_generator, get_generators_list,
    create_generator, delete_generator
)

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
        user_name=user_name or (run.user.full_name if run.user else None),
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    gen = await get_or_create_default_generator(db, generator_id=generator_id, facility_id=facility_id)
    return gen


@router.get("/list", response_model=List[GeneratorOut])
async def list_all_generators(
    facility_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Список усіх генераторів (з можливістю фільтрації за об'єктом)"""
    return await get_generators_list(db, facility_id=facility_id)


@router.post("", response_model=GeneratorOut, status_code=status.HTTP_201_CREATED)
async def create_new_generator_api(
    data: GeneratorCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
    """Створити новий генератор"""
    client_ip = get_client_ip(request)
    return await create_generator(db, data, current_user.id, client_ip)


@router.delete("/{generator_id}")
async def delete_generator_api(
    generator_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
    """Видалити генератор"""
    client_ip = get_client_ip(request)
    return await delete_generator(db, generator_id, current_user.id, client_ip)


@router.post("/wizard", response_model=GeneratorOut)
async def setup_wizard(
    setup_data: GeneratorWizardSetup,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:configure"))
):
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
    gen = await get_or_create_default_generator(db, generator_id=data.generator_id)
    run = await start_generator(
        db=db,
        generator_id=gen.id,
        user_id=current_user.id,
        fuel_level_l=data.fuel_level_l,
        ip_address=get_client_ip(request)
    )
    return run_to_out(run, user_name=current_user.full_name)


@router.post("/stop", response_model=GeneratorRunOut)
async def api_stop_generator(
    data: GeneratorStopRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("generator:stop"))
):
    gen = await get_or_create_default_generator(db, generator_id=data.generator_id)
    run = await stop_generator(
        db=db,
        generator_id=gen.id,
        user_id=current_user.id,
        stop_data=data,
        ip_address=get_client_ip(request)
    )
    return run_to_out(run, user_name=current_user.full_name)


@router.get("/active-run", response_model=Optional[GeneratorRunOut])
async def get_active_run(
    generator_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(GeneratorRun).where(GeneratorRun.status == "RUNNING")
    if generator_id:
        query = query.where(GeneratorRun.generator_id == generator_id)
    query = query.order_by(GeneratorRun.id.desc())
    res = await db.execute(query)
    run = res.scalars().first()
    if not run:
        return None
    return run_to_out(run)


@router.get("/runs", response_model=List[GeneratorRunOut])
async def list_runs(
    generator_id: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(GeneratorRun)
    if generator_id:
        query = query.where(GeneratorRun.generator_id == generator_id)
    query = query.order_by(GeneratorRun.id.desc()).limit(limit)
    res = await db.execute(query)
    runs = res.scalars().all()
    return [run_to_out(r) for r in runs]
