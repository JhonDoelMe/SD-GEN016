import time
import sys
import platform
import datetime
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.config import settings
from backend.app.core.timezone import now_facility
from backend.app.models.facility import Facility
from backend.app.models.generator import Generator

try:
    import psutil
except ImportError:
    psutil = None

# Track server process start time
SERVER_START_TIME = time.time()

router = APIRouter(prefix="/system", tags=["Система та моніторинг"])


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

    # 1. CPU & RAM & Disk metrics
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

    # 2. Database connectivity & counts
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
        "timezone": settings.FACILITY_TIMEZONE,
        "environment": {
            "platform": f"{platform.system()} {platform.release()}",
            "python_version": platform.python_version(),
            "facilities_count": facility_count,
            "generators_count": generator_count
        }
    }
