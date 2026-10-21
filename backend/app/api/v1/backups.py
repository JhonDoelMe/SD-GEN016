from typing import List, Optional, Dict, Any
from pathlib import Path
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.api.deps import get_current_superadmin, get_client_ip
from backend.app.models.user import User
from backend.app.services.audit_service import log_audit
from backend.app.services.settings_service import (
    load_system_settings,
    update_system_settings,
    get_runtime_setting,
)
from backend.app.services.backup_service import (
    get_backup_dir,
    create_backup,
    list_backups,
    delete_backup,
    rotate_backups,
    format_file_size,
)

router = APIRouter(prefix="/backups", tags=["Резервне копіювання та бекапи"])


class CreateBackupRequest(BaseModel):
    backup_type: Optional[str] = None
    type: Optional[str] = None
    notes: Optional[str] = Field(default="", max_length=255)
    note: Optional[str] = Field(default="", max_length=255)

    def get_backup_type(self) -> str:
        raw = (self.backup_type or self.type or "full").strip().lower()
        if raw in ("partial", "db_only"):
            return "partial"
        return "full"

    def get_notes(self) -> str:
        return (self.notes or self.note or "").strip()


class BackupSettingsUpdateRequest(BaseModel):
    backup_auto_enabled: Optional[bool] = None
    backup_schedule_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    backup_frequency: Optional[str] = Field(default=None, pattern=r"^(daily|weekly)$")
    backup_retention_count: Optional[int] = Field(default=None, ge=1, le=100)
    backup_default_type: Optional[str] = Field(default=None, pattern=r"^(full|partial|db_only)$")


@router.get("", response_model=Dict[str, Any])
async def get_backups_list(
    current_user: User = Depends(get_current_superadmin),
):
    """Отримати список усіх наявних резервних копій (Лише для SuperAdmin)."""
    backups = list_backups()
    total_size_bytes = sum(b.get("size_bytes", 0) for b in backups)
    return {
        "count": len(backups),
        "total_count": len(backups),
        "total_size_bytes": total_size_bytes,
        "total_size_formatted": format_file_size(total_size_bytes),
        "backups": backups,
    }


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def trigger_manual_backup(
    payload: CreateBackupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    """Створити нову резервну копію системи вручну (Лише для SuperAdmin)."""
    client_ip = get_client_ip(request)
    chosen_type = payload.get_backup_type()
    chosen_notes = payload.get_notes()

    manifest = await create_backup(
        session=db,
        backup_type=chosen_type,
        creator=current_user.login,
        creator_ip=client_ip,
        notes=chosen_notes,
    )
    return {
        **manifest,
        "message": f"{manifest.get('backup_type_ua', 'Резервну копію')} успішно створено!",
        "backup": manifest,
        "manifest": manifest,
    }


@router.get("/settings", response_model=Dict[str, Any])
async def get_backup_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    """Отримати налаштування автоматичного створення бекапів."""
    settings_dict = await load_system_settings(db)
    raw_type = settings_dict.get("backup_default_type", "full")
    clean_type = "partial" if raw_type in ("partial", "db_only") else "full"
    data = {
        "backup_auto_enabled": settings_dict.get("backup_auto_enabled", False),
        "backup_schedule_time": settings_dict.get("backup_schedule_time", "03:00"),
        "backup_frequency": settings_dict.get("backup_frequency", "daily"),
        "backup_retention_count": settings_dict.get("backup_retention_count", 7),
        "backup_default_type": clean_type,
    }
    return {
        **data,
        "settings": data,
    }


@router.put("/settings", response_model=Dict[str, Any])
async def update_backup_settings(
    payload: BackupSettingsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    """Оновити налаштування розкладу автоматичного створення бекапів."""
    update_data = {}
    if payload.backup_auto_enabled is not None:
        update_data["backup_auto_enabled"] = payload.backup_auto_enabled
    if payload.backup_schedule_time is not None:
        update_data["backup_schedule_time"] = payload.backup_schedule_time
    if payload.backup_frequency is not None:
        update_data["backup_frequency"] = payload.backup_frequency
    if payload.backup_retention_count is not None:
        update_data["backup_retention_count"] = payload.backup_retention_count
    if payload.backup_default_type is not None:
        update_data["backup_default_type"] = payload.backup_default_type

    if update_data:
        client_ip = get_client_ip(request)
        await update_system_settings(
            db=db,
            updates=update_data,
        )
        await log_audit(
            db=db,
            action="BACKUP_SETTINGS_UPDATE",
            entity_type="system_settings",
            entity_id="backups",
            details={"updated_settings": update_data},
            ip_address=client_ip
        )

    return await get_backup_settings(db=db, current_user=current_user)


@router.get("/{filename}/download")
async def download_backup_file(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    """Завантажити zip-архів резервної копії (Лише для SuperAdmin)."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".zip") or not safe_name.startswith("backup_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некоректне ім'я файлу резервної копії"
        )

    backup_dir = get_backup_dir()
    file_path = backup_dir / safe_name

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл резервної копії не знайдено на сервері"
        )

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="BACKUP_DOWNLOAD",
        entity_type="backup",
        entity_id=safe_name,
        details={"message": f"Завантажено архів резервної копії '{safe_name}'"},
        ip_address=client_ip
    )

    return FileResponse(
        path=str(file_path),
        media_type="application/zip",
        filename=safe_name,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'}
    )


@router.delete("/{filename}", response_model=Dict[str, Any])
async def remove_backup_file(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    """Видалити архів резервної копії (Лише для SuperAdmin)."""
    client_ip = get_client_ip(request)
    try:
        success = await delete_backup(
            session=db,
            filename=filename,
            user_login=current_user.login,
            ip_address=client_ip,
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл резервної копії не знайдено"
        )

    return {"status": "success", "message": f"Резервну копію '{filename}' успішно видалено"}
