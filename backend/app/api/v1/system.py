import time
import sys
import platform
import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.config import settings
from backend.app.core.timezone import now_facility
from backend.app.core.security import verify_password
from backend.app.api.deps import get_current_user, get_current_admin, get_client_ip
from backend.app.models.user import User
from backend.app.models.facility import Facility
from backend.app.models.generator import Generator
from backend.app.services.audit_service import log_audit
from backend.app.services.settings_service import (
    load_system_settings,
    update_system_settings,
    get_runtime_timezone,
    get_runtime_setting,
    get_fuel_prices_info,
    refresh_internet_fuel_prices,
    perform_system_reset,
)

try:
    import psutil
except ImportError:
    psutil = None

# Track server process start time
SERVER_START_TIME = time.time()

router = APIRouter(prefix="/system", tags=["Система, налаштування та моніторинг"])


class SystemSettingsUpdateRequest(BaseModel):
    organization_name: Optional[str] = Field(default=None, max_length=150)
    facility_timezone: Optional[str] = Field(default=None, max_length=64)
    work_schedule_start: Optional[str] = Field(default=None, max_length=10)
    work_schedule_end: Optional[str] = Field(default=None, max_length=10)
    enforce_work_schedule: Optional[bool] = None
    default_maintenance_interval_hours: Optional[float] = Field(default=None, gt=0)
    fuel_price_a95: Optional[float] = Field(default=None, ge=0)
    fuel_price_a92: Optional[float] = Field(default=None, ge=0)
    fuel_price_dp: Optional[float] = Field(default=None, ge=0)
    auto_fetch_fuel_prices: Optional[bool] = None
    apply_to_all_generators: bool = Field(
        default=False,
        description="Якщо True — синхронізувати часовий пояс, графік роботи та інтервал ТО для всіх генераторів і об'єктів"
    )


class SystemResetRequest(BaseModel):
    mode: str = Field(
        ...,
        description="Режим очищення: facility_clean | reports_clean | settings_reset | factory_reset"
    )
    facility_id: Optional[int] = Field(default=None, description="ID об'єкта (для режиму facility_clean)")
    admin_password: str = Field(..., min_length=1, description="Пароль поточного адміністратора для підтвердження")
    confirm_code: str = Field(..., description="Кодове слово підтвердження: ОЧИСТИТИ або RESET")


def format_uptime(seconds: float) -> str:
    sec = int(seconds)
    days = sec // 86400
    hours = (sec % 86400) // 3600
    minutes = (sec % 3600) // 60
    parts = []
    if days > 0:
        parts.append(f"{days} д")
    if hours > 0 or days > 0:
        parts.append(f"{hours} год")
    parts.append(f"{minutes} хв")
    return " ".join(parts)


@router.get("/status")
async def get_system_status(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Повертає реальний статус стану сервера:
    CPU, оперативна пам'ять, диск, час безвідмовної роботи (uptime), статус бази даних.
    """
    now = time.time()
    uptime_sec = max(0.0, now - SERVER_START_TIME)

    cpu_percent = 0.0
    ram_percent = 0.0
    ram_used_mb = 0.0
    ram_total_mb = 0.0
    disk_percent = 0.0

    if psutil:
        try:
            cpu_percent = round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            cpu_percent = 0.0

        try:
            vm = psutil.virtual_memory()
            ram_percent = round(vm.percent, 1)
            ram_used_mb = round(vm.used / (1024 * 1024), 1)
            ram_total_mb = round(vm.total / (1024 * 1024), 1)
        except Exception:
            pass

        try:
            disk = psutil.disk_usage(sys.executable[0:3] if sys.platform == 'win32' else '/')
            disk_percent = round(disk.percent, 1)
        except Exception:
            pass

    db_status = "connected"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    facility_count = 0
    generator_count = 0
    try:
        f_res = await db.execute(select(func.count(Facility.id)))
        facility_count = f_res.scalar_one() or 0
        g_res = await db.execute(select(func.count(Generator.id)))
        generator_count = g_res.scalar_one() or 0
    except Exception:
        pass

    return {
        "status": "online",
        "cpu": {
            "percent": cpu_percent
        },
        "memory": {
            "percent": ram_percent,
            "used_mb": ram_used_mb,
            "total_mb": ram_total_mb
        },
        "disk": {
            "percent": disk_percent
        },
        "uptime": {
            "seconds": int(uptime_sec),
            "formatted": format_uptime(uptime_sec)
        },
        "database": {
            "status": db_status
        },
        "server_time": now_facility().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": get_runtime_timezone(),
        "organization_name": get_runtime_setting("organization_name", "MAXI-UA LLC"),
        "environment": {
            "platform": f"{platform.system()} {platform.release()}",
            "python_version": platform.python_version(),
            "facilities_count": facility_count,
            "generators_count": generator_count
        }
    }


@router.get("/fuel-prices")
async def get_fuel_prices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Повертає актуальні ціни на паливо (налаштовані вручну, з інтернету та діючі для авторозрахунку).
    Доступно для всіх авторизованих користувачів (використовується у формі оприбуткування палива).
    """
    await load_system_settings(db)
    if get_runtime_setting("auto_fetch_fuel_prices", True) and not get_runtime_setting("internet_prices_updated_at"):
        try:
            await refresh_internet_fuel_prices(db)
        except Exception:
            pass
    return get_fuel_prices_info()


@router.post("/fuel-prices/refresh")
async def force_refresh_fuel_prices(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Примусове оновлення середніх цін на паливо по Україні з інтернету (тільки для Адміністратора).
    """
    info = await refresh_internet_fuel_prices(db)
    await log_audit(
        db=db,
        action="FUEL_PRICES_REFRESHED",
        entity_type="SystemSetting",
        entity_id="fuel_prices",
        user_id=current_user.id,
        details={
            "source": info.get("internet_prices_source"),
            "updated_at": info.get("internet_prices_updated_at"),
            "a95": info["fuels"]["А-95"]["internet_price"],
            "a92": info["fuels"]["А-92"]["internet_price"],
            "dp": info["fuels"]["ДП"]["internet_price"],
        },
        ip_address=get_client_ip(request)
    )
    await db.commit()
    return info


@router.get("/settings")
async def get_admin_system_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Отримання всіх динамічних налаштувань системи (тільки для Адміністратора).
    """
    data = await load_system_settings(db)
    return {
        "settings": data,
        "fuel_prices": get_fuel_prices_info(),
    }


@router.put("/settings")
async def update_admin_system_settings(
    payload: SystemSettingsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Збереження динамічних налаштувань системи: графік роботи, часовий пояс, організація,
    ціни на паливо та інтервали ТО (тільки для Адміністратора).
    """
    updates: Dict[str, Any] = {}
    for field_name in (
        "organization_name",
        "facility_timezone",
        "work_schedule_start",
        "work_schedule_end",
        "enforce_work_schedule",
        "default_maintenance_interval_hours",
        "fuel_price_a95",
        "fuel_price_a92",
        "fuel_price_dp",
        "auto_fetch_fuel_prices",
    ):
        val = getattr(payload, field_name)
        if val is not None:
            updates[field_name] = val

    try:
        updated = await update_system_settings(
            db=db,
            updates=updates,
            apply_to_all_generators=payload.apply_to_all_generators
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await log_audit(
        db=db,
        action="SYSTEM_SETTINGS_UPDATED",
        entity_type="SystemSetting",
        entity_id="global",
        user_id=current_user.id,
        details={
            "updates": updates,
            "applied_to_all_generators": payload.apply_to_all_generators
        },
        ip_address=get_client_ip(request)
    )
    await db.commit()

    return {
        "message": "Системні налаштування успішно збережено",
        "settings": updated,
        "fuel_prices": get_fuel_prices_info(),
    }


@router.post("/reset")
async def reset_system_or_clean_db(
    payload: SystemResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Очищення журналів/звітів або повне заводське скидання бази даних (тільки для Адміністратора з підтвердженням пароля).
    """
    if payload.confirm_code.strip().upper() not in ("ОЧИСТИТИ", "RESET"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Невірне кодове слово підтвердження. Введіть 'ОЧИСТИТИ' або 'RESET'."
        )

    if not verify_password(payload.admin_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Невірний пароль адміністратора. Операцію скасовано."
        )

    if payload.mode == "factory_reset" and not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Повне заводське скидання БД (factory_reset) дозволено виключно Головному Системному Адміністратору (SuperAdmin)."
        )

    try:
        result = await perform_system_reset(
            db=db,
            mode=payload.mode,
            user_id=current_user.id,
            facility_id=payload.facility_id,
            ip_address=get_client_ip(request)
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
