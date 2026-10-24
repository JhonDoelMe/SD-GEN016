from typing import List
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.schemas.facility import FacilityCreate, FacilityUpdate, FacilityOut
from backend.app.api.deps import (
    get_current_user,
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
    if not is_user_admin_or_super(current_user) and current_user.facility_id:
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
    current_user: User = Depends(require_permission("facility:configure"))
):
    """Видалити об'єкт"""
    verify_facility_access(current_user, facility_id)
    client_ip = get_client_ip(request)
    return await delete_facility(db, facility_id, current_user.id, cascade=cascade, ip_address=client_ip)
