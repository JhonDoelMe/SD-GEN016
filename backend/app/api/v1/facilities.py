from typing import List
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.schemas.facility import FacilityCreate, FacilityUpdate, FacilityOut
from backend.app.api.deps import get_current_user, get_client_ip
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
    """Отримати перелік усіх об'єктів/локацій"""
    return await get_all_facilities(db)


@router.post("", response_model=FacilityOut, status_code=status.HTTP_201_CREATED)
async def add_facility(
    data: FacilityCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
    return await get_facility_by_id(db, facility_id)


@router.put("/{facility_id}", response_model=FacilityOut)
async def edit_facility(
    facility_id: int,
    data: FacilityUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Оновити параметри об'єкту"""
    client_ip = get_client_ip(request)
    return await update_facility(db, facility_id, data, current_user.id, client_ip)


@router.delete("/{facility_id}")
async def remove_facility(
    facility_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Видалити об'єкт"""
    client_ip = get_client_ip(request)
    return await delete_facility(db, facility_id, current_user.id, client_ip)
