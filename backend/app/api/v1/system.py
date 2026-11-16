import json
import time
import sys
import asyncio
import platform
import datetime
import httpx
from typing import Dict, Any, Optional, List, Literal
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.config import settings
from backend.app.core.secrets import SECRET_MASK
from backend.app.core.timezone import now_facility
from backend.app.core.security import verify_password
from backend.app.api.deps import get_current_user, get_current_admin, get_current_superadmin, require_permission, get_client_ip
from backend.app.models.user import User
from backend.app.models.facility import Facility
from backend.app.models.generator import Generator
from backend.app.services.audit_service import log_audit
from backend.app.services.settings_service import (
    SERVER_ONLY_SETTING_KEYS,
    SECRET_SETTING_KEYS,
    load_system_settings,
    update_system_settings,
    get_runtime_timezone,
    get_runtime_setting,
    get_effective_str_setting,
    get_effective_int_setting,
    get_effective_primary_domain,
    get_setting_source,
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


class EmailTestRequest(BaseModel):
    recipient: str = Field(..., max_length=150)
    provider: str = Field(default="failover", description="failover | primary | fallback")
    # On-the-fly config parameters from form testing
    smtp_primary_host: Optional[str] = None
    smtp_primary_port: Optional[int] = None
    smtp_primary_user: Optional[str] = None
    smtp_primary_password: Optional[str] = None
    smtp_primary_ssl: Optional[bool] = None
    smtp_primary_from: Optional[str] = None
    smtp_fallback_enabled: Optional[bool] = None
    smtp_fallback_host: Optional[str] = None
    smtp_fallback_port: Optional[int] = None
    smtp_fallback_user: Optional[str] = None
    smtp_fallback_password: Optional[str] = None
    smtp_fallback_ssl: Optional[bool] = None
    smtp_fallback_from: Optional[str] = None


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
    # Operational Safeguards
    max_continuous_run_hours: Optional[float] = Field(default=None, ge=1.0, le=48.0)
    auto_stop_on_schedule_end: Optional[bool] = None
    notify_running_heartbeat: Optional[bool] = None
    heartbeat_interval_hours: Optional[float] = Field(default=None, ge=1.0, le=24.0)
    warmup_reminder_enabled: Optional[bool] = None
    warmup_idle_days: Optional[int] = Field(default=None, ge=1, le=90)
    warmup_duration_minutes: Optional[int] = Field(default=None, ge=5, le=60)
    warmup_cold_temp_c: Optional[float] = Field(default=None, ge=-40.0, le=10.0)
    warmup_trigger_mode: Optional[Literal["any", "idle", "cold", "both"]] = None
    fuel_receipt_max_liters_warning: Optional[float] = Field(default=None, gt=0)
    fuel_receipt_min_price: Optional[float] = Field(default=None, ge=0)
    fuel_receipt_max_price: Optional[float] = Field(default=None, gt=0)
    # SMTP & Failover Settings
    smtp_enabled: Optional[bool] = None
    smtp_primary_host: Optional[str] = Field(default=None, max_length=150)
    smtp_primary_port: Optional[int] = Field(default=None, ge=1, le=65535)
    smtp_primary_user: Optional[str] = Field(default=None, max_length=150)
    smtp_primary_password: Optional[str] = Field(default=None, max_length=150)
    smtp_primary_ssl: Optional[bool] = None
    smtp_primary_from: Optional[str] = Field(default=None, max_length=150)
    smtp_fallback_enabled: Optional[bool] = None
    smtp_fallback_host: Optional[str] = Field(default=None, max_length=150)
    smtp_fallback_port: Optional[int] = Field(default=None, ge=1, le=65535)
    smtp_fallback_user: Optional[str] = Field(default=None, max_length=150)
    smtp_fallback_password: Optional[str] = Field(default=None, max_length=150)
    smtp_fallback_ssl: Optional[bool] = None
    smtp_fallback_from: Optional[str] = Field(default=None, max_length=150)
    email_notify_password_change: Optional[bool] = None
    email_notify_safety_stop: Optional[bool] = None
    email_notify_empty_tank: Optional[bool] = None
    email_notify_low_fuel: Optional[bool] = None
    email_notify_outside_schedule: Optional[bool] = None
    email_notify_critical_fault: Optional[bool] = None
    email_notify_maintenance_due: Optional[bool] = None
    email_weekly_report_enabled: Optional[bool] = None
    email_weekly_recipients: Optional[str] = Field(default=None, max_length=500)
    email_weekly_send_day: Optional[int] = Field(default=None, ge=0, le=6)
    email_weekly_send_time: Optional[str] = Field(default=None, max_length=10)
    # Default Facility, Generator & Stock Binding
    default_facility_id: Optional[int] = None
    default_generator_id: Optional[int] = None
    default_fuel_stock_id: Optional[int] = None
    email_weekly_facility_id: Optional[int] = None
    email_weekly_generator_id: Optional[int] = None
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
async def get_system_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Повертає реальний статус стану сервера:
    CPU, оперативна пам'ять, диск, час безвідмовної роботи (uptime), статус бази даних.
    Чутливі деталі ядра ОС та точні патч-версії Python приховано для захисту від fingerprinting.
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
        "default_facility_id": get_runtime_setting("default_facility_id"),
        "default_generator_id": get_runtime_setting("default_generator_id"),
        "default_fuel_stock_id": get_runtime_setting("default_fuel_stock_id"),
        "environment": {
            "platform": platform.system(),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
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
    provider: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Примусове оновлення середніх цін на паливо з офіційних табло АЗК WOG / OKKO (тільки для Адміністратора).
    """
    prov = (provider or "all").lower().strip()
    info = await refresh_internet_fuel_prices(db, provider=prov)
    await log_audit(
        db=db,
        action="FUEL_PRICES_REFRESHED",
        entity_type="SystemSetting",
        entity_id="fuel_prices",
        user_id=current_user.id,
        details={
            "provider": prov,
            "source_wog": info.get("internet_prices_source"),
            "updated_at_wog": info.get("internet_prices_updated_at"),
            "source_okko": info.get("okko_prices_source"),
            "updated_at_okko": info.get("okko_prices_updated_at"),
            "wog_dp": info.get("fuels", {}).get("ДП", {}).get("internet_price"),
            "okko_dp": info.get("okko_fuels", {}).get("ДП", {}).get("internet_price"),
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
    Паролі поштових шлюзів маскуються для запобігання витоку.
    """
    data = await load_system_settings(db)
    masked = {k: v for k, v in data.items() if k not in SERVER_ONLY_SETTING_KEYS}
    if masked.get("smtp_primary_password"):
        masked["smtp_primary_password"] = SECRET_MASK
    if masked.get("smtp_fallback_password"):
        masked["smtp_fallback_password"] = SECRET_MASK
    return {
        "settings": masked,
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
    ціни на паливо, інтервали ТО, запобіжники та поштові шлюзи (тільки для Адміністратора).
    """
    updates: Dict[str, Any] = {}
    all_fields = (
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
        "max_continuous_run_hours",
        "auto_stop_on_schedule_end",
        "notify_running_heartbeat",
        "heartbeat_interval_hours",
        "warmup_reminder_enabled",
        "warmup_idle_days",
        "warmup_duration_minutes",
        "warmup_cold_temp_c",
        "warmup_trigger_mode",
        "fuel_receipt_max_liters_warning",
        "fuel_receipt_min_price",
        "fuel_receipt_max_price",
        "smtp_enabled",
        "smtp_primary_host",
        "smtp_primary_port",
        "smtp_primary_user",
        "smtp_primary_password",
        "smtp_primary_ssl",
        "smtp_primary_from",
        "smtp_fallback_enabled",
        "smtp_fallback_host",
        "smtp_fallback_port",
        "smtp_fallback_user",
        "smtp_fallback_password",
        "smtp_fallback_ssl",
        "smtp_fallback_from",
        "email_notify_password_change",
        "email_notify_safety_stop",
        "email_notify_empty_tank",
        "email_notify_low_fuel",
        "email_notify_outside_schedule",
        "email_notify_critical_fault",
        "email_notify_maintenance_due",
        "email_weekly_report_enabled",
        "email_weekly_recipients",
        "email_weekly_send_day",
        "email_weekly_send_time",
        "default_facility_id",
        "default_generator_id",
        "default_fuel_stock_id",
        "email_weekly_facility_id",
        "email_weekly_generator_id",
    )
    submitted = payload.model_dump(exclude_unset=True)
    for field_name in all_fields:
        if field_name in submitted:
            val = submitted[field_name]
            # Prevent overwriting real passwords with masked asterisks or empty string if unchanged
            if field_name in ("smtp_primary_password", "smtp_fallback_password") and val in ("********", ""):
                continue
            updates[field_name] = val

    try:
        updated = await update_system_settings(
            db=db,
            updates=updates,
            apply_to_all_generators=payload.apply_to_all_generators
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    from backend.app.services.audit_service import sanitize_audit_details
    await log_audit(
        db=db,
        action="SYSTEM_SETTINGS_UPDATED",
        entity_type="SystemSetting",
        entity_id="global",
        user_id=current_user.id,
        details={
            "updates": sanitize_audit_details(updates),
            "applied_to_all_generators": payload.apply_to_all_generators
        },
        ip_address=get_client_ip(request)
    )
    await db.commit()

    masked_updated = dict(updated)
    if masked_updated.get("smtp_primary_password"):
        masked_updated["smtp_primary_password"] = "********"
    if masked_updated.get("smtp_fallback_password"):
        masked_updated["smtp_fallback_password"] = "********"
    return {
        "message": "Системні налаштування успішно збережено",
        "settings": masked_updated,
        "fuel_prices": get_fuel_prices_info(),
    }


@router.post("/reset")
async def reset_system_or_clean_db(
    payload: SystemResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin)
) -> Dict[str, Any]:
    """
    Очищення журналів/звітів або повне заводське скидання бази даних (тільки для Адміністратора з підтвердженням пароля).
    """
    if payload.confirm_code.strip().upper() not in ("ОЧИСТИТИ", "RESET"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Невірне кодове слово підтвердження. Введіть 'ОЧИСТИТИ' або 'RESET'."
        )

    if not await asyncio.to_thread(verify_password, payload.admin_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Невірний пароль адміністратора. Операцію скасовано."
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


@router.post("/email/test")
async def test_email_configuration(
    payload: EmailTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Тестова перевірка конфігурації SMTP (Primary, Fallback або Failover).
    Доступно тільки для адміністраторів системи.
    """
    to_addr = payload.recipient.strip()
    if not to_addr or "@" not in to_addr:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Вкажіть коректну адресу електронної пошти")

    from backend.app.services.email_service import send_email_with_failover, _wrap_html_template
    import html as html_lib

    force_prov = payload.provider if payload.provider in ("primary", "fallback") else None
    subject = "Тестове сповіщення — Service Desk Бензинового Генератора"

    content = f"""
    <div class="success-box">
      <strong>✅ Тест SMTP пройдено успішно!</strong><br>
      Це тестове повідомлення підтверджує працездатність поштового шлюзу сповіщень.
    </div>
    <p>Параметри тесту:</p>
    <ul>
      <li><strong>Отримувач:</strong> {html_lib.escape(to_addr)}</li>
      <li><strong>Режим відправки:</strong> {html_lib.escape(payload.provider)}</li>
      <li><strong>Ініціатор:</strong> {html_lib.escape(current_user.full_name)} ({html_lib.escape(current_user.login)})</li>
      <li><strong>Час перевірки:</strong> {now_facility().strftime('%d.%m.%Y %H:%M:%S')}</li>
    </ul>
    """
    html_body = _wrap_html_template("Тест SMTP", content)

    # For testing, honor on-the-fly config parameters passed from the admin UI
    config_override: Dict[str, Any] = {"smtp_enabled": True}
    for attr in (
        "smtp_primary_host", "smtp_primary_port", "smtp_primary_user", "smtp_primary_password",
        "smtp_primary_ssl", "smtp_primary_from", "smtp_fallback_enabled", "smtp_fallback_host",
        "smtp_fallback_port", "smtp_fallback_user", "smtp_fallback_password", "smtp_fallback_ssl", "smtp_fallback_from"
    ):
        val = getattr(payload, attr, None)
        if val is not None:
            config_override[attr] = val

    from backend.app.services.email_service import validate_smtp_target
    for prefix in ("smtp_primary", "smtp_fallback"):
        h_override = config_override.get(f"{prefix}_host")
        p_override = config_override.get(f"{prefix}_port")
        if h_override is not None or p_override is not None:
            host_to_check = h_override if h_override is not None else str(get_runtime_setting(f"{prefix}_host", "") or "")
            port_to_check = p_override if p_override is not None else int(get_runtime_setting(f"{prefix}_port", 587) or 587)
            if host_to_check:
                try:
                    validate_smtp_target(host_to_check, port_to_check)
                except ValueError as exc:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    start_t = time.time()
    res = await send_email_with_failover(
        to_addr=to_addr,
        subject=subject,
        html_body=html_body,
        db=db,
        force_provider=force_prov,
        config_override=config_override
    )

    duration_ms = int(round((time.time() - start_t) * 1000))
    res["duration_ms"] = duration_ms
    res["tested_at"] = now_facility().strftime('%d.%m.%Y %H:%M:%S')

    await log_audit(
        db=db,
        action="SMTP_TEST_SENT",
        entity_type="SystemSetting",
        entity_id="email",
        user_id=current_user.id,
        details={"recipient": to_addr, "provider": payload.provider, "result": res},
        ip_address=get_client_ip(request)
    )
    await db.commit()

    return res


@router.post("/email/weekly-digest/send")
async def send_weekly_digest_manual(
    request: Request,
    recipient: Optional[str] = None,
    facility_id: Optional[int] = None,
    generator_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
) -> Dict[str, Any]:
    """
    Примусова генерація та відправка щотижневого звіту Excel на вказану адресу або список адрес із налаштувань.
    """
    from backend.app.services.report_service import generate_excel_report
    from backend.app.services.email_service import send_weekly_digest_email

    recipients_str = recipient or str(get_runtime_setting("email_weekly_recipients", "")).strip()
    if not recipients_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не вказано адреси отримувачів щотижневого звіту"
        )

    rec_list = [r.strip() for r in recipients_str.replace(";", ",").split(",") if r.strip()]
    if not rec_list:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Список адрес отримувачів порожній")

    target_fac = facility_id or get_runtime_setting("email_weekly_facility_id") or get_runtime_setting("default_facility_id")
    target_gen = generator_id or get_runtime_setting("email_weekly_generator_id") or get_runtime_setting("default_generator_id")
    excel_bytes = await generate_excel_report(db=db, facility_id=target_fac, generator_id=target_gen)
    now_dt = now_facility()
    week_ago = now_dt - datetime.timedelta(days=7)
    period_label = f"{week_ago.strftime('%d.%m.%Y')} — {now_dt.strftime('%d.%m.%Y')}"

    res = await send_weekly_digest_email(
        recipients=rec_list,
        excel_bytes=excel_bytes,
        period_label=period_label,
        summary_text=f"Звіт надіслано адміністратором {current_user.full_name} ({current_user.login}).",
        db=db,
        config_override={"smtp_enabled": True}
    )

    await log_audit(
        db=db,
        action="WEEKLY_DIGEST_EMAIL_SENT",
        entity_type="SystemSetting",
        entity_id="email",
        user_id=current_user.id,
        details={"recipients": rec_list, "result": res},
        ip_address=get_client_ip(request)
    )
    await db.commit()

    if res.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Помилка відправки щотижневого звіту: {res.get('error')}"
        )

    return {"message": "Щотижневий звіт успішно надіслано", "result": res}


# ==========================================
# Server & Integrations Settings (SuperAdmin ONLY)
# ==========================================

class ServerConfigUpdateRequest(BaseModel):
    primary_domain: Optional[str] = Field(None, max_length=255)
    allowed_hosts: Optional[str] = Field(None, max_length=2000)
    cors_origins: Optional[str] = Field(None, max_length=2000)
    access_token_expire_minutes: Optional[int] = Field(None, ge=5, le=525600)
    login_max_attempts: Optional[int] = Field(None, ge=1, le=100)
    login_lockout_seconds: Optional[int] = Field(None, ge=1, le=86400)
    openweather_api_key: Optional[str] = Field(None, max_length=512)
    weather_cache_minutes: Optional[int] = Field(None, ge=1, le=1440)
    alerts_in_ua_token: Optional[str] = Field(None, max_length=1024)
    ukraine_alarm_api_key: Optional[str] = Field(None, max_length=1024)
    alerts_cache_seconds: Optional[int] = Field(None, ge=5, le=3600)
    ukraine_alarm_cache_seconds: Optional[int] = Field(None, ge=15, le=3600)
    firebase_service_account_json: Optional[str] = Field(None, max_length=65536)
    clear_keys: List[str] = Field(default_factory=list)


class IntegrationTestRequest(BaseModel):
    provider: Literal["openweather", "alerts_in_ua", "ukraine_alarm", "firebase"]
    value: Optional[str] = Field(None, max_length=65536)


def _build_server_config_payload() -> Dict[str, Any]:
    from backend.app.services.fcm_service import _load_service_account, is_fcm_configured

    sa = _load_service_account()
    db_fb_raw = str(get_runtime_setting("firebase_service_account_json", "") or "").strip()
    env_fb_raw = str(getattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "") or "").strip()
    if db_fb_raw:
        fb_source = "db"
    elif env_fb_raw:
        fb_source = "env"
    elif sa:
        fb_source = "file"
    else:
        fb_source = "default"

    owm_val = get_effective_str_setting("openweather_api_key", "OPENWEATHER_API_KEY", "")
    aiu_val = get_effective_str_setting("alerts_in_ua_token", "ALERTS_IN_UA_TOKEN", "")
    ua_val = get_effective_str_setting("ukraine_alarm_api_key", "UKRAINE_ALARM_API_KEY", "")

    config = {
        "primary_domain": get_effective_primary_domain(),
        "allowed_hosts": get_effective_str_setting("allowed_hosts", "ALLOWED_HOSTS", ""),
        "cors_origins": get_effective_str_setting("cors_origins", "CORS_ORIGINS", ""),
        "access_token_expire_minutes": get_effective_int_setting(
            "access_token_expire_minutes", "ACCESS_TOKEN_EXPIRE_MINUTES", settings.ACCESS_TOKEN_EXPIRE_MINUTES, min_value=5
        ),
        "login_max_attempts": get_effective_int_setting(
            "login_max_attempts", "LOGIN_MAX_ATTEMPTS", settings.LOGIN_MAX_ATTEMPTS, min_value=1
        ),
        "login_lockout_seconds": get_effective_int_setting(
            "login_lockout_seconds", "LOGIN_LOCKOUT_SECONDS", settings.LOGIN_LOCKOUT_SECONDS, min_value=1
        ),
        "openweather_api_key": SECRET_MASK if owm_val else "",
        "weather_cache_minutes": get_effective_int_setting(
            "weather_cache_minutes", "WEATHER_CACHE_MINUTES", settings.WEATHER_CACHE_MINUTES, min_value=1
        ),
        "alerts_in_ua_token": SECRET_MASK if aiu_val else "",
        "ukraine_alarm_api_key": SECRET_MASK if ua_val else "",
        "alerts_cache_seconds": get_effective_int_setting(
            "alerts_cache_seconds", "ALERTS_CACHE_SECONDS", settings.ALERTS_CACHE_SECONDS, min_value=5
        ),
        "ukraine_alarm_cache_seconds": get_effective_int_setting(
            "ukraine_alarm_cache_seconds", "UKRAINE_ALARM_CACHE_SECONDS", settings.UKRAINE_ALARM_CACHE_SECONDS, min_value=15
        ),
        "firebase_service_account_json": SECRET_MASK if (db_fb_raw or env_fb_raw) else "",
        "firebase_configured": is_fcm_configured(),
        "firebase_project_id": sa.get("project_id", "") if isinstance(sa, dict) else "",
        "firebase_client_email": sa.get("client_email", "") if isinstance(sa, dict) else "",
    }

    sources = {
        "primary_domain": get_setting_source("primary_domain"),
        "allowed_hosts": get_setting_source("allowed_hosts"),
        "cors_origins": get_setting_source("cors_origins"),
        "access_token_expire_minutes": get_setting_source("access_token_expire_minutes"),
        "login_max_attempts": "db",
        "login_lockout_seconds": "db",
        "openweather_api_key": get_setting_source("openweather_api_key"),
        "weather_cache_minutes": get_setting_source("weather_cache_minutes"),
        "alerts_in_ua_token": get_setting_source("alerts_in_ua_token"),
        "ukraine_alarm_api_key": get_setting_source("ukraine_alarm_api_key"),
        "alerts_cache_seconds": get_setting_source("alerts_cache_seconds"),
        "ukraine_alarm_cache_seconds": get_setting_source("ukraine_alarm_cache_seconds"),
        "firebase_service_account_json": fb_source,
    }

    db_url = str(getattr(settings, "DATABASE_URL", "") or "")
    db_dialect = "PostgreSQL" if "postgresql" in db_url.lower() else ("SQLite" if "sqlite" in db_url.lower() else "Custom")
    runtime = {
        "app_env": settings.APP_ENV,
        "database_dialect": db_dialect,
        "upload_dir": settings.UPLOAD_DIR,
        "backup_dir": settings.BACKUP_DIR,
        "facility_timezone": get_runtime_timezone(),
    }
    return {"config": config, "sources": sources, "runtime": runtime}


@router.get("/server-config")
async def get_server_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> Dict[str, Any]:
    """Отримати конфігурацію сервера та зовнішніх інтеграцій (тільки SuperAdmin)."""
    await load_system_settings(db)
    return _build_server_config_payload()


@router.put("/server-config")
async def update_server_config(
    payload: ServerConfigUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> Dict[str, Any]:
    """Оновити параметри сервера та інтеграцій (ключі шифруються в БД, тільки SuperAdmin)."""
    await load_system_settings(db)
    submitted = payload.model_dump(exclude_unset=True)
    clear_keys = set(submitted.pop("clear_keys", []) or [])

    allowed_server_fields = set(SERVER_ONLY_SETTING_KEYS) | {"login_max_attempts", "login_lockout_seconds"}
    secret_server_keys = SECRET_SETTING_KEYS.intersection(allowed_server_fields)

    updates: Dict[str, Any] = {}
    reset_fcm = False

    for key in allowed_server_fields:
        if key in clear_keys:
            if key in ("access_token_expire_minutes", "weather_cache_minutes", "alerts_cache_seconds", "ukraine_alarm_cache_seconds"):
                updates[key] = None
            elif key == "login_max_attempts":
                updates[key] = 5
            elif key == "login_lockout_seconds":
                updates[key] = 300
            else:
                updates[key] = ""
            if key == "firebase_service_account_json":
                reset_fcm = True
            continue

        if key not in submitted:
            continue

        val = submitted[key]
        if key in secret_server_keys:
            if val is None or str(val).strip() in ("", SECRET_MASK):
                continue
            val_clean = str(val).strip()
            if key == "firebase_service_account_json":
                try:
                    parsed_sa = json.loads(val_clean)
                except Exception as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Некоректний JSON файлу облікових даних Firebase: {exc}",
                    )
                if not isinstance(parsed_sa, dict) or not (
                    parsed_sa.get("project_id") and parsed_sa.get("private_key") and parsed_sa.get("client_email")
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Firebase JSON повинен містити поля project_id, client_email та private_key",
                    )
                val_clean = json.dumps(parsed_sa, ensure_ascii=False)
                reset_fcm = True
            updates[key] = val_clean
        elif key == "primary_domain":
            dom = str(val or "").strip().lower()
            dom = dom.removeprefix("https://").removeprefix("http://").strip("/")
            updates[key] = dom
        elif key in ("allowed_hosts", "cors_origins"):
            updates[key] = str(val or "").strip()
        else:
            updates[key] = val

    if updates:
        try:
            await update_system_settings(db=db, updates=updates)
        except ValueError as ve:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    if reset_fcm:
        from backend.app.services.fcm_service import reset_fcm_token_cache
        reset_fcm_token_cache()

    audit_fields = {
        k: ("[REDACTED]" if k in secret_server_keys and updates[k] else updates[k])
        for k in updates
    }
    await log_audit(
        db=db,
        action="SERVER_CONFIG_UPDATED",
        entity_type="SystemSetting",
        entity_id="server-config",
        user_id=current_user.id,
        details={"updated_keys": list(updates.keys()), "updates": audit_fields},
        ip_address=get_client_ip(request),
    )
    await db.commit()

    res = _build_server_config_payload()
    res["message"] = "Налаштування сервера та інтеграцій збережено"
    return res


@router.post("/server-config/test-integration")
async def test_server_integration(
    payload: IntegrationTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> Dict[str, Any]:
    """Перевірка працездатності API-ключів та Firebase Service Account (тільки SuperAdmin)."""
    await load_system_settings(db)
    start_t = time.time()
    raw_val = (payload.value or "").strip()
    if raw_val == SECRET_MASK:
        raw_val = ""

    if payload.provider == "openweather":
        api_key = raw_val or get_effective_str_setting("openweather_api_key", "OPENWEATHER_API_KEY", "")
        if not api_key:
            return {"status": "error", "message": "API ключ OpenWeatherMap не вказано"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"q": "Kyiv", "appid": api_key, "units": "metric", "lang": "uk"},
                )
            ms = int(round((time.time() - start_t) * 1000))
            if r.status_code == 200:
                data = r.json()
                temp = data.get("main", {}).get("temp")
                return {
                    "status": "ok",
                    "message": f"З'єднання успішне (Київ: {temp}°C)",
                    "duration_ms": ms,
                }
            return {
                "status": "error",
                "message": f"OpenWeatherMap повернув код HTTP {r.status_code}",
                "duration_ms": ms,
            }
        except Exception as exc:
            return {"status": "error", "message": f"Помилка з'єднання: {exc}"}

    if payload.provider == "alerts_in_ua":
        token_val = raw_val or get_effective_str_setting("alerts_in_ua_token", "ALERTS_IN_UA_TOKEN", "")
        if not token_val:
            return {"status": "error", "message": "Токен alerts.in.ua не вказано"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    "https://api.alerts.in.ua/v1/alerts/active.json",
                    headers={"Authorization": f"Bearer {token_val}"},
                )
            ms = int(round((time.time() - start_t) * 1000))
            if r.status_code in (200, 304):
                return {"status": "ok", "message": f"Токен alerts.in.ua дійсний (HTTP {r.status_code})", "duration_ms": ms}
            return {"status": "error", "message": f"alerts.in.ua повернув HTTP {r.status_code}", "duration_ms": ms}
        except Exception as exc:
            return {"status": "error", "message": f"Помилка з'єднання: {exc}"}

    if payload.provider == "ukraine_alarm":
        ua_key = raw_val or get_effective_str_setting("ukraine_alarm_api_key", "UKRAINE_ALARM_API_KEY", "")
        if not ua_key:
            return {"status": "error", "message": "API ключ UkraineAlarm не вказано"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    "https://api.ukrainealarm.com/api/v3/alerts",
                    headers={"Authorization": ua_key},
                )
            ms = int(round((time.time() - start_t) * 1000))
            if r.status_code in (200, 304):
                return {"status": "ok", "message": f"Ключ UkraineAlarm дійсний (HTTP {r.status_code})", "duration_ms": ms}
            if r.status_code == 429:
                return {"status": "ok", "message": "Ключ розпізнано (активний rate-limit 429 API сервісу)", "duration_ms": ms}
            return {"status": "error", "message": f"UkraineAlarm повернув HTTP {r.status_code}", "duration_ms": ms}
        except Exception as exc:
            return {"status": "error", "message": f"Помилка з'єднання: {exc}"}

    if payload.provider == "firebase":
        from backend.app.services.fcm_service import _load_service_account, _get_fcm_access_token
        if raw_val:
            try:
                sa = json.loads(raw_val)
            except Exception as exc:
                return {"status": "error", "message": f"Некоректний JSON: {exc}"}
            if not isinstance(sa, dict) or not (sa.get("project_id") and sa.get("private_key") and sa.get("client_email")):
                return {"status": "error", "message": "JSON не містить project_id, client_email або private_key"}
            return {
                "status": "ok",
                "message": f"JSON валідний (проєкт: {sa.get('project_id')}). Збережіть налаштування для активації.",
                "duration_ms": int(round((time.time() - start_t) * 1000)),
            }

        sa = _load_service_account()
        if not sa:
            return {"status": "error", "message": "Firebase Service Account не налаштовано"}
        access_tok, project_id = await _get_fcm_access_token()
        ms = int(round((time.time() - start_t) * 1000))
        if access_tok and project_id:
            return {
                "status": "ok",
                "message": f"Firebase OAuth2 авторизація успішна (проєкт: {project_id})",
                "duration_ms": ms,
            }
        return {
            "status": "error",
            "message": "Не вдалося отримати OAuth2 токен Firebase (перевірте private_key або мережу)",
            "duration_ms": ms,
        }

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невідомий провайдер")
