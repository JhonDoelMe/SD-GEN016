"""
Initial Web Setup Wizard API (`/api/v1/setup/*`) for Zero-.env fresh deployments.

Automatically locks permanently (`403 Forbidden`) once the initial SuperAdmin
and system configuration have been finalized.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from backend.app.api.deps import get_client_ip
from backend.app.config import DEFAULT_SECRET_KEY, settings
from backend.app.core.bootstrap import (
    generate_instance_secret,
    is_setup_required,
    set_setup_required,
    update_instance_config,
)
from backend.app.core.security import get_password_hash
from backend.app.database import (
    AsyncSessionLocal,
    Base,
    get_engine,
    probe_database_connection,
    reinit_database_engine,
)
from backend.app.models.user import User
from backend.app.schemas.auth import validate_password_complexity
from backend.app.services.audit_service import log_audit
from backend.app.services.init_service import (
    ensure_default_facility_and_resources,
    ensure_permissions_and_roles,
)
from backend.app.services.settings_service import load_system_settings, update_system_settings

router = APIRouter(prefix="/setup", tags=["Початкове налаштування (Setup Wizard)"])

_SETUP_LOCK = asyncio.Lock()
_SAFE_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_LOGIN_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SetupDatabaseConfig(BaseModel):
    db_type: Literal["sqlite", "postgresql"] = "sqlite"
    sqlite_filename: str = Field(default="service_desk.db", max_length=100)
    pg_host: str = Field(default="localhost", max_length=255)
    pg_port: int = Field(default=5432, ge=1, le=65535)
    pg_user: str = Field(default="sd_user", max_length=120)
    pg_password: str = Field(default="", max_length=256)
    pg_db: str = Field(default="sd_gen016", max_length=120)

    def build_database_url(self) -> str:
        if self.db_type == "sqlite":
            fname = Path(self.sqlite_filename or "service_desk.db").name.strip()
            if not fname or not _SAFE_DB_NAME_RE.match(fname):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Некоректна назва файлу SQLite (дозволені лише латинські літери, цифри, '.', '-', '_')",
                )
            if not fname.endswith((".db", ".sqlite", ".sqlite3")):
                fname = f"{fname}.db"
            return f"sqlite+aiosqlite:///./data/{fname}"

        host = (self.pg_host or "").strip()
        user = (self.pg_user or "").strip()
        dbname = (self.pg_db or "").strip()
        if not host or not user or not dbname:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для PostgreSQL обов'язково вкажіть хост, користувача та назву бази даних",
            )
        import urllib.parse
        u_enc = urllib.parse.quote_plus(user)
        p_enc = urllib.parse.quote_plus(self.pg_password or "")
        return f"postgresql+asyncpg://{u_enc}:{p_enc}@{host}:{int(self.pg_port)}/{dbname}"


class SetupCompleteRequest(SetupDatabaseConfig):
    organization_name: str = Field(..., min_length=2, max_length=120)
    primary_domain: Optional[str] = Field(default="", max_length=255)
    facility_timezone: str = Field(default="Europe/Kyiv", max_length=64)
    facility_name: str = Field(default="Основний об'єкт", min_length=2, max_length=120)
    facility_address: str = Field(default="Головна локація", min_length=2, max_length=255)
    admin_login: str = Field(..., min_length=3, max_length=60)
    admin_email: str = Field(..., min_length=5, max_length=150)
    admin_full_name: str = Field(..., min_length=2, max_length=120)
    admin_password: str = Field(..., min_length=8, max_length=128)
    openweather_api_key: Optional[str] = Field(default="", max_length=512)
    alerts_in_ua_token: Optional[str] = Field(default="", max_length=1024)
    ukraine_alarm_api_key: Optional[str] = Field(default="", max_length=1024)

    @field_validator("admin_login")
    @classmethod
    def check_login(cls, v: str) -> str:
        clean = v.strip()
        if not _LOGIN_RE.match(clean):
            raise ValueError("Логін може містити лише латинські літери, цифри та символи _ . -")
        return clean

    @field_validator("admin_email")
    @classmethod
    def check_email(cls, v: str) -> str:
        clean = v.strip()
        if not _EMAIL_RE.match(clean):
            raise ValueError("Некоректний формат email")
        return clean

    @field_validator("admin_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_complexity(v)


def _require_setup_open() -> None:
    if not is_setup_required():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Майстер початкового налаштування вже завершено та заблоковано",
        )


@router.get("/status")
async def get_setup_status() -> Dict[str, Any]:
    """Check whether initial Web Setup Wizard is currently open."""
    return {
        "setup_required": is_setup_required(),
        "current_dialect": "sqlite" if settings.is_sqlite else "postgresql",
    }


@router.post("/test-db")
async def test_setup_database(payload: SetupDatabaseConfig) -> Dict[str, Any]:
    """Verify candidate SQLite or PostgreSQL connectivity during initial setup."""
    _require_setup_open()
    dsn = payload.build_database_url()
    ok, msg = await probe_database_connection(dsn)
    return {"ok": ok, "message": msg}


@router.post("/complete")
async def complete_initial_setup(
    payload: SetupCompleteRequest,
    request: Request,
) -> Dict[str, Any]:
    """
    Execute one-time Clean Setup Wizard:
    1. Test & switch DB engine if requested.
    2. Initialize schema cleanly (refusing non-empty user tables).
    3. Create SuperAdmin account, starter facility/generator/fuel stock.
    4. Save domain, org, and encrypted API keys in DB.
    5. Lock setup permanently via `instance.config.json` (`setup_completed=True`).
    """
    async with _SETUP_LOCK:
        _require_setup_open()

        # Validate timezone
        tz_clean = (payload.facility_timezone or "Europe/Kyiv").strip()
        try:
            ZoneInfo(tz_clean)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Невідомий часовий пояс: {tz_clean}",
            )

        target_dsn = payload.build_database_url()
        ok, msg = await probe_database_connection(target_dsn)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Не вдалося підключитися до бази даних: {msg}",
            )

        await reinit_database_engine(target_dsn)

        from backend.app.main import ensure_schema_updates
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(ensure_schema_updates)

        async with AsyncSessionLocal() as db:
            user_count = int((await db.execute(select(func.count(User.id)))).scalar() or 0)
            if user_count > 0:
                set_setup_required(False)
                update_instance_config({"setup_completed": True, "database_url": settings.DATABASE_URL})
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Обрана база даних вже містить облікові записи. Майстер налаштування заблоковано для захисту даних.",
                )

            roles_map = await ensure_permissions_and_roles(db)
            default_fac = await ensure_default_facility_and_resources(
                db,
                facility_name=payload.facility_name.strip(),
                facility_address=payload.facility_address.strip(),
                timezone_name=tz_clean,
            )

            superadmin = User(
                login=payload.admin_login,
                email=payload.admin_email,
                password_hash=await asyncio.to_thread(get_password_hash, payload.admin_password),
                full_name=payload.admin_full_name.strip(),
                is_active=True,
                is_superadmin=True,
                facility_id=default_fac.id if default_fac else None,
            )
            if "superadmin" in roles_map:
                superadmin.roles.append(roles_map["superadmin"])
            db.add(superadmin)
            await db.flush()

            dom_clean = (payload.primary_domain or "").strip().lower()
            dom_clean = dom_clean.removeprefix("https://").removeprefix("http://").strip("/")

            # Ensure strong APP_SECRET_KEY before encrypting any API keys
            if not settings.APP_SECRET_KEY or settings.APP_SECRET_KEY == DEFAULT_SECRET_KEY or len(settings.APP_SECRET_KEY) < 32:
                settings.APP_SECRET_KEY = generate_instance_secret()

            settings_updates: Dict[str, Any] = {
                "organization_name": payload.organization_name.strip(),
                "facility_timezone": tz_clean,
            }
            if dom_clean:
                settings_updates["primary_domain"] = dom_clean
            if payload.openweather_api_key and payload.openweather_api_key.strip():
                settings_updates["openweather_api_key"] = payload.openweather_api_key.strip()
            if payload.alerts_in_ua_token and payload.alerts_in_ua_token.strip():
                settings_updates["alerts_in_ua_token"] = payload.alerts_in_ua_token.strip()
            if payload.ukraine_alarm_api_key and payload.ukraine_alarm_api_key.strip():
                settings_updates["ukraine_alarm_api_key"] = payload.ukraine_alarm_api_key.strip()

            await load_system_settings(db)
            await update_system_settings(db, settings_updates)

            await log_audit(
                db=db,
                action="SYSTEM_INITIAL_SETUP_COMPLETED",
                entity_type="System",
                entity_id="setup",
                user_id=superadmin.id,
                details={
                    "organization_name": payload.organization_name.strip(),
                    "primary_domain": dom_clean or settings.PRIMARY_DOMAIN,
                    "db_type": payload.db_type,
                    "admin_login": payload.admin_login,
                },
                ip_address=get_client_ip(request),
            )
            await db.commit()

        update_instance_config(
            {
                "app_secret_key": settings.APP_SECRET_KEY,
                "database_url": settings.DATABASE_URL,
                "app_env": "production" if settings.is_production else settings.APP_ENV,
                "setup_completed": True,
            }
        )
        set_setup_required(False)

        return {
            "status": "ok",
            "message": "Систему успішно налаштовано! Перехід на сторінку входу...",
            "redirect": "/",
        }
