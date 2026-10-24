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
from backend.app.api.deps import get_current_user, get_current_admin, get_current_superadmin, require_permission, get_client_ip
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
    email_notify_critical_fault: Optional[bool] = None
    email_notify_maintenance_due: Optional[bool] = None
    email_weekly_report_enabled: Optional[bool] = None
    email_weekly_recipients: Optional[str] = Field(default=None, max_length=500)
    email_weekly_send_day: Optional[int] = Field(default=None, ge=0, le=6)
    email_weekly_send_time: Optional[str] = Field(default=None, max_length=10)
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
    db: AsyncSession = Depends(get_db)
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
    Паролі поштових шлюзів маскуються для запобігання витоку.
    """
    data = await load_system_settings(db)
    masked = dict(data)
    if masked.get("smtp_primary_password"):
        masked["smtp_primary_password"] = "********"
    if masked.get("smtp_fallback_password"):
        masked["smtp_fallback_password"] = "********"
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
        "email_notify_critical_fault",
        "email_notify_maintenance_due",
        "email_weekly_report_enabled",
        "email_weekly_recipients",
        "email_weekly_send_day",
        "email_weekly_send_time",
    )
    for field_name in all_fields:
        val = getattr(payload, field_name, None)
        if val is not None:
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

    start_t = time.time()
    orig_smtp_enabled = bool(get_runtime_setting("smtp_enabled", False))
    from backend.app.services.settings_service import set_runtime_setting
    set_runtime_setting("smtp_enabled", True)
    try:
        res = await send_email_with_failover(
            to_addr=to_addr,
            subject=subject,
            html_body=html_body,
            db=db,
            force_provider=force_prov,
            config_override=config_override
        )
    finally:
        set_runtime_setting("smtp_enabled", orig_smtp_enabled)

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

    excel_bytes = await generate_excel_report(db=db)
    now_dt = datetime.datetime.now()
    week_ago = now_dt - datetime.timedelta(days=7)
    period_label = f"{week_ago.strftime('%d.%m.%Y')} — {now_dt.strftime('%d.%m.%Y')}"

    orig_smtp_enabled = bool(get_runtime_setting("smtp_enabled", False))
    from backend.app.services.settings_service import set_runtime_setting
    set_runtime_setting("smtp_enabled", True)
    try:
        res = await send_weekly_digest_email(
            recipients=rec_list,
            excel_bytes=excel_bytes,
            period_label=period_label,
            summary_text=f"Звіт надіслано адміністратором {current_user.full_name} ({current_user.login}).",
            db=db
        )
    finally:
        set_runtime_setting("smtp_enabled", orig_smtp_enabled)

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
