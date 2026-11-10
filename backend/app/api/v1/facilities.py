from typing import List
from fastapi import APIRouter, Depends, Request, Response, status, HTTPException
from pydantic import BaseModel
from backend.app.models.facility import Facility
from backend.app.services.yasno_service import fetch_raw_yasno_schedule, get_facility_outage_schedule
from backend.app.services.weather_service import get_facility_weather
from backend.app.services.alert_service import get_facility_alert, set_demo_alert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.schemas.facility import FacilityCreate, FacilityUpdate, FacilityOut
from backend.app.api.deps import (
    get_current_user,
    get_current_superadmin,
    require_permission,
    get_client_ip,
    is_user_admin_or_super,
    verify_facility_access,
)
from backend.app.services.facility_service import (
    get_all_facilities, get_facility_by_id, create_facility,
    update_facility, delete_facility
)

router = APIRouter(prefix="/facilities", tags=["Об'єкти (Multi-site)"])


@router.get("", response_model=List[FacilityOut])
async def list_facilities(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати перелік об'єктів/локацій (для операторів — лише їхній закріплений об'єкт)"""
    all_facs = await get_all_facilities(db)
    if not is_user_admin_or_super(current_user):
        if not current_user.facility_id:
            return []
        return [f for f in all_facs if f.id == current_user.facility_id]
    return all_facs


@router.post("", response_model=FacilityOut, status_code=status.HTTP_201_CREATED)
async def add_facility(
    data: FacilityCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("facility:configure"))
):
    """Створити новий об'єкт (локацію)"""
    client_ip = get_client_ip(request)
    return await create_facility(db, data, current_user.id, client_ip)


@router.get("/{facility_id}", response_model=FacilityOut)
async def get_facility(
    facility_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати дані конкретного об'єкту"""
    verify_facility_access(current_user, facility_id)
    return await get_facility_by_id(db, facility_id)


@router.put("/{facility_id}", response_model=FacilityOut)
async def edit_facility(
    facility_id: int,
    data: FacilityUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("facility:configure"))
):
    """Оновити параметри об'єкту"""
    verify_facility_access(current_user, facility_id)
    client_ip = get_client_ip(request)
    return await update_facility(db, facility_id, data, current_user.id, client_ip)


@router.delete("/{facility_id}")
async def remove_facility(
    facility_id: int,
    request: Request,
    cascade: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin)
):
    """Видалити об'єкт (доступно виключно для SuperAdmin)"""
    verify_facility_access(current_user, facility_id)
    client_ip = get_client_ip(request)
    return await delete_facility(db, facility_id, current_user.id, cascade=cascade, ip_address=client_ip)


@router.get("/{facility_id}/outage-schedule")
async def get_facility_outage(
    facility_id: int,
    force_refresh: bool = False,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати розпарсений графік відключень YASNO для конкретного об'єкта"""
    verify_facility_access(current_user, facility_id)
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    fac = await db.get(Facility, facility_id)
    if not fac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Об'єкт #{facility_id} не знайдено")

    if not fac.yasno_enabled or not fac.yasno_group:
        return get_facility_outage_schedule(fac)

    raw_data = await fetch_raw_yasno_schedule(
        region_id=fac.yasno_region_id or 3,
        dso_id=fac.yasno_dso_id or 301,
        force_refresh=force_refresh
    )
    return get_facility_outage_schedule(fac, raw_schedule=raw_data)


@router.get("/{facility_id}/weather")
async def get_facility_weather_data(
    facility_id: int,
    force: bool = False,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати поточну погоду для об'єкта"""
    verify_facility_access(current_user, facility_id)
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return await get_facility_weather(db, facility_id, force=force)


@router.get("/{facility_id}/alert")
async def get_facility_alert_data(
    facility_id: int,
    force: bool = False,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати статус повітряної тривоги для об'єкта"""
    verify_facility_access(current_user, facility_id)
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return await get_facility_alert(db, facility_id, force=force)


@router.get("/{facility_id}/status-indicators")
async def get_facility_indicators(
    facility_id: int,
    force: bool = False,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Отримати об'єднані індикатори погоди та тривог в одному швидкому запиті"""
    verify_facility_access(current_user, facility_id)
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    weather = await get_facility_weather(db, facility_id, force=force)
    alert = await get_facility_alert(db, facility_id, force=force)
    return {
        "weather": weather,
        "alert": alert
    }


class DemoAlertRequest(BaseModel):
    level: str = "green"  # green, yellow, red
    threat_type: str = "none"


@router.post("/demo-alert")
async def trigger_demo_alert(
    data: DemoAlertRequest,
    current_user: User = Depends(get_current_superadmin)
):
    """Тестовий перемикач рівнів тривог для перевірки UI (доступно для SuperAdmin)"""
    set_demo_alert(data.level, data.threat_type)
    return {"ok": True, "level": data.level, "threat_type": data.threat_type}
