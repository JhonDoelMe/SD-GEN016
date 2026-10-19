import json
import re
import datetime
import urllib.request
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, Tuple
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.settings import SystemSetting
from backend.app.models.facility import Facility
from backend.app.models.generator import Generator, GeneratorSchedule, GeneratorRun
from backend.app.models.fuel import FuelStock, FuelReceipt, FuelTransfer
from backend.app.models.maintenance import MaintenanceSchedule, MaintenanceRecord
from backend.app.models.fault import Fault
from backend.app.models.audit import AuditLog, SystemAdjustment
from backend.app.models.user import User

# Default Ukrainian retail fuel prices fallback (UAH per liter) if offline
DEFAULT_INTERNET_PRICES: Dict[str, float] = {
    "А-95": 56.50,
    "А-92": 53.90,
    "ДП": 52.80,
}

# Default dynamic system settings (stored in DB table `system_settings`)
DEFAULT_SYSTEM_SETTINGS: Dict[str, Any] = {
    "organization_name": "MAXI-UA LLC",
    "facility_timezone": "Europe/Kyiv",
    "work_schedule_start": "08:00",
    "work_schedule_end": "20:00",
    "enforce_work_schedule": True,
    "default_maintenance_interval_hours": 300.0,
    "login_max_attempts": 5,
    "login_lockout_seconds": 300,
    # Fuel pricing configuration (0.0 means "not manually set -> use internet price")
    "fuel_price_a95": 0.0,
    "fuel_price_a92": 0.0,
    "fuel_price_dp": 0.0,
    "auto_fetch_fuel_prices": True,
    # Cached internet prices
    "internet_price_a95": DEFAULT_INTERNET_PRICES["А-95"],
    "internet_price_a92": DEFAULT_INTERNET_PRICES["А-92"],
    "internet_price_dp": DEFAULT_INTERNET_PRICES["ДП"],
    "internet_prices_updated_at": "",
    "internet_prices_source": "Ринковий індикатор АЗС України",
}

# In-memory cache of runtime settings for fast synchronous reads (e.g. timezone.py)
RUNTIME_SETTINGS: Dict[str, Any] = dict(DEFAULT_SYSTEM_SETTINGS)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def get_runtime_setting(key: str, default: Any = None) -> Any:
    return RUNTIME_SETTINGS.get(key, DEFAULT_SYSTEM_SETTINGS.get(key, default))


def get_runtime_timezone() -> str:
    tz = str(RUNTIME_SETTINGS.get("facility_timezone") or "Europe/Kyiv").strip()
    try:
        ZoneInfo(tz)
        return tz
    except Exception:
        return "Europe/Kyiv"


def fetch_ukraine_fuel_prices_online(timeout: float = 4.0) -> Tuple[Dict[str, float], str, bool]:
    """
    Отримує актуальні середні роздрібні ціни на пальне в Україні (А-95, А-92, ДП)
    з відкритих фінансових джерел (Мінфін / AutoRia).
    Повертає: (prices_dict, source_label, is_live_from_internet)
    """
    prices = dict(DEFAULT_INTERNET_PRICES)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    # Source 1: index.minfin.com.ua/ua/markets/fuel/
    try:
        req = urllib.request.Request("https://index.minfin.com.ua/ua/markets/fuel/", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        found_any = False
        patterns = {
            "А-95": [
                r"Бензин\s+А-95(?![\s+]*преміум|\+)[^<]*</a>\s*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>\s*<b>\s*(\d{2}[.,]\d{2})\s*</b>",
                r"А-95(?![\s+]*преміум|\+).*?(\d{2}[.,]\d{2})",
            ],
            "А-92": [
                r"Бензин\s+А-92[^<]*</a>\s*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>\s*<b>\s*(\d{2}[.,]\d{2})\s*</b>",
                r"А-92.*?(\d{2}[.,]\d{2})",
            ],
            "ДП": [
                r"Дизельне\s+паливо(?![\s+]*преміум|\+)[^<]*</a>\s*</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>\s*<b>\s*(\d{2}[.,]\d{2})\s*</b>",
                r"Дизельне\s+паливо.*?(\d{2}[.,]\d{2})",
            ],
        }
        for fuel_key, regex_list in patterns.items():
            for pat in regex_list:
                m = re.search(pat, html, flags=re.IGNORECASE | re.DOTALL)
                if m:
                    val = float(m.group(1).replace(",", "."))
                    if 30.0 <= val <= 150.0:
                        prices[fuel_key] = round(val, 2)
                        found_any = True
                        break

        if found_any:
            return prices, "Мінфін (середні ціни АЗС України)", True
    except Exception:
        pass

    # Source 2: auto.ria.com/uk/toplivo/
    try:
        req = urllib.request.Request("https://auto.ria.com/uk/toplivo/", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        found_any = False
        for fuel_key, label in [("А-95", r"А-95(?!\+)"), ("А-92", r"А-92"), ("ДП", r"ДП(?!\+)")]:
            m = re.search(label + r".{1,250}?(\d{2}[.,]\d{2})", html, flags=re.IGNORECASE | re.DOTALL)
            if m:
                val = float(m.group(1).replace(",", "."))
                if 30.0 <= val <= 150.0:
                    prices[fuel_key] = round(val, 2)
                    found_any = True

        if found_any:
            return prices, "Auto.ria (середні ціни АЗС України)", True
    except Exception:
        pass

    # Fallback: preserve existing cached internet prices if valid, else default Ukrainian market benchmark
    for k, setting_key in [("А-95", "internet_price_a95"), ("А-92", "internet_price_a92"), ("ДП", "internet_price_dp")]:
        cached_val = float(RUNTIME_SETTINGS.get(setting_key) or 0.0)
        if 30.0 <= cached_val <= 150.0:
            prices[k] = round(cached_val, 2)

    return prices, "Ринковий індикатор АЗС України (резерв)", False


async def load_system_settings(db: AsyncSession) -> Dict[str, Any]:
    """
    Завантажує системні налаштування з таблиці `system_settings`,
    ініціалізує відсутні ключі значеннями за замовчуванням та оновлює RUNTIME_SETTINGS.
    """
    res = await db.execute(select(SystemSetting))
    rows = res.scalars().all()
    existing_map = {r.key: r for r in rows}

    merged: Dict[str, Any] = dict(DEFAULT_SYSTEM_SETTINGS)
    needs_flush = False

    for k, default_val in DEFAULT_SYSTEM_SETTINGS.items():
        if k in existing_map:
            try:
                merged[k] = json.loads(existing_map[k].value_json)
            except Exception:
                merged[k] = default_val
        else:
            db.add(SystemSetting(
                key=k,
                value_json=json.dumps(default_val, ensure_ascii=False),
                description=f"Системний параметр {k}"
            ))
            needs_flush = True

    if needs_flush:
        await db.commit()

    RUNTIME_SETTINGS.update(merged)
    return dict(RUNTIME_SETTINGS)


async def update_system_settings(
    db: AsyncSession,
    updates: Dict[str, Any],
    apply_to_all_generators: bool = False
) -> Dict[str, Any]:
    """
    Оновлює системні налаштування в БД та в RUNTIME_SETTINGS.
    Опціонально синхронізує часовий пояс та робочий графік для всіх об'єктів та генераторів.
    """
    await load_system_settings(db)

    res = await db.execute(select(SystemSetting))
    existing_map = {r.key: r for r in res.scalars().all()}

    # Validate timezone if provided
    if "facility_timezone" in updates and updates["facility_timezone"]:
        tz_str = str(updates["facility_timezone"]).strip()
        try:
            ZoneInfo(tz_str)
            updates["facility_timezone"] = tz_str
        except Exception:
            raise ValueError(f"Невідомий часовий пояс: {tz_str}")

    # Validate schedule times if provided
    for time_key in ("work_schedule_start", "work_schedule_end"):
        if time_key in updates and updates[time_key] is not None:
            t_val = str(updates[time_key]).strip()
            if not _TIME_RE.match(t_val):
                raise ValueError(f"Некоректний формат часу '{t_val}' для {time_key} (очікується ГГ:ХХ)")
            updates[time_key] = t_val

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    for k, val in updates.items():
        if k not in DEFAULT_SYSTEM_SETTINGS:
            continue
        RUNTIME_SETTINGS[k] = val
        json_str = json.dumps(val, ensure_ascii=False)
        if k in existing_map:
            existing_map[k].value_json = json_str
            existing_map[k].updated_at = now
        else:
            db.add(SystemSetting(
                key=k,
                value_json=json_str,
                description=f"Системний параметр {k}",
                updated_at=now
            ))

    if apply_to_all_generators:
        tz = RUNTIME_SETTINGS.get("facility_timezone", "Europe/Kyiv")
        w_start = RUNTIME_SETTINGS.get("work_schedule_start", "08:00")
        w_end = RUNTIME_SETTINGS.get("work_schedule_end", "20:00")
        maint_int = float(RUNTIME_SETTINGS.get("default_maintenance_interval_hours", 300.0))

        # Update all facilities timezone
        await db.execute(update(Facility).values(timezone=tz, updated_at=now))
        # Update all generators timezone
        await db.execute(update(Generator).values(timezone=tz, updated_at=now))

        # Update or create schedules for all generators
        gens_res = await db.execute(select(Generator))
        for gen in gens_res.scalars().all():
            await db.execute(delete(GeneratorSchedule).where(GeneratorSchedule.generator_id == gen.id))
            db.add(GeneratorSchedule(
                generator_id=gen.id,
                weekday=-1,
                start_time=w_start,
                end_time=w_end,
                timezone=tz,
                is_active=True
            ))
            # Also update maintenance interval if schedule exists
            m_res = await db.execute(select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id == gen.id))
            m_sched = m_res.scalars().first()
            if m_sched and maint_int > 0:
                m_sched.interval_hours = maint_int

    await db.commit()
    return dict(RUNTIME_SETTINGS)


async def refresh_internet_fuel_prices(db: AsyncSession) -> Dict[str, Any]:
    """
    Запитує актуальні ціни на пальне з інтернету та зберігає їх у SystemSetting.
    """
    prices, source_label, is_live = fetch_ukraine_fuel_prices_online()
    now_str = datetime.datetime.now(ZoneInfo(get_runtime_timezone())).strftime("%Y-%m-%d %H:%M:%S")
    updates = {
        "internet_price_a95": prices.get("А-95", DEFAULT_INTERNET_PRICES["А-95"]),
        "internet_price_a92": prices.get("А-92", DEFAULT_INTERNET_PRICES["А-92"]),
        "internet_price_dp": prices.get("ДП", DEFAULT_INTERNET_PRICES["ДП"]),
        "internet_prices_updated_at": now_str,
        "internet_prices_source": source_label,
    }
    await update_system_settings(db, updates)
    return get_fuel_prices_info()


def get_fuel_prices_info() -> Dict[str, Any]:
    """
    Повертає повну інформацію про ціни на пальне:
    налаштовані вручну, ціни з інтернету та ефективні (діючі) ціни для розрахунку.
    """
    mapping = [
        ("А-95", "fuel_price_a95", "internet_price_a95"),
        ("А-92", "fuel_price_a92", "internet_price_a92"),
        ("ДП", "fuel_price_dp", "internet_price_dp"),
    ]
    fuels: Dict[str, Dict[str, Any]] = {}
    for label, conf_key, net_key in mapping:
        conf_val = float(RUNTIME_SETTINGS.get(conf_key) or 0.0)
        net_val = float(RUNTIME_SETTINGS.get(net_key) or DEFAULT_INTERNET_PRICES[label])
        if conf_val > 0:
            effective = round(conf_val, 2)
            source = "settings"
            source_name = "Встановлено в налаштуваннях"
        else:
            effective = round(net_val, 2)
            source = "internet"
            source_name = str(RUNTIME_SETTINGS.get("internet_prices_source") or "Інтернет (АЗС України)")

        fuels[label] = {
            "fuel_type": label,
            "effective_price": effective,
            "configured_price": round(conf_val, 2),
            "internet_price": round(net_val, 2),
            "source": source,
            "source_name": source_name,
        }

    return {
        "fuels": fuels,
        "auto_fetch_fuel_prices": bool(RUNTIME_SETTINGS.get("auto_fetch_fuel_prices", True)),
        "internet_prices_updated_at": RUNTIME_SETTINGS.get("internet_prices_updated_at") or "",
        "internet_prices_source": RUNTIME_SETTINGS.get("internet_prices_source") or "Ринковий індикатор АЗС України",
    }


async def resolve_fuel_price_per_liter(db: AsyncSession, fuel_type: str) -> Tuple[float, str]:
    """
    Визначає ціну за літр для оприбуткування палива, якщо сума чека не була вказана:
    1) Якщо в налаштуваннях задана ціна > 0 для цього типу палива -> використовує її.
    2) Інакше якщо увімкнено автооновлення і ціни з інтернету ще не оновлювалися -> оновлює з інтернету та повертає інтернет-ціну.
    """
    await load_system_settings(db)
    ft = (fuel_type or "А-95").strip().upper()
    if "92" in ft:
        norm_ft = "А-92"
        conf_key = "fuel_price_a92"
        net_key = "internet_price_a92"
    elif "ДП" in ft or "ДИЗ" in ft or "DIESEL" in ft:
        norm_ft = "ДП"
        conf_key = "fuel_price_dp"
        net_key = "internet_price_dp"
    else:
        norm_ft = "А-95"
        conf_key = "fuel_price_a95"
        net_key = "internet_price_a95"

    conf_price = float(RUNTIME_SETTINGS.get(conf_key) or 0.0)
    if conf_price > 0:
        return round(conf_price, 2), "system_settings"

    # Try refreshing from internet if never updated or if auto_fetch is enabled and cache is empty
    if RUNTIME_SETTINGS.get("auto_fetch_fuel_prices", True) and not RUNTIME_SETTINGS.get("internet_prices_updated_at"):
        try:
            await refresh_internet_fuel_prices(db)
        except Exception:
            pass

    net_price = float(RUNTIME_SETTINGS.get(net_key) or DEFAULT_INTERNET_PRICES.get(norm_ft, 56.50))
    if net_price <= 0:
        net_price = DEFAULT_INTERNET_PRICES.get(norm_ft, 56.50)

    return round(net_price, 2), "internet"


async def perform_system_reset(
    db: AsyncSession,
    mode: str,
    user_id: int,
    facility_id: Optional[int] = None,
    ip_address: Optional[str] = None
) -> Dict[str, Any]:
    """
    Виконує очищення експлуатаційних даних, скидання налаштувань або повне заводське скидання БД.
    Доступні режими (`mode`):
      - `facility_clean`: очищення журналів/звітів та обнулення лічильників обраного об'єкта (`facility_id`).
      - `reports_clean`: очищення всіх журналів та звітів по всій системі зі збереженням об'єктів, генераторів і користувачів.
      - `settings_reset`: скидання системних налаштувань до стандартних заводських параметрів.
      - `factory_reset`: повне очищення БД до заводського стану (перед продажем або передачею в експлуатацію).
    """
    from backend.app.services.audit_service import log_audit

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    if mode == "facility_clean":
        if not facility_id:
            raise ValueError("Для режиму 'facility_clean' необхідно вказати facility_id")

        gens_res = await db.execute(select(Generator).where(Generator.facility_id == facility_id))
        gens = gens_res.scalars().all()
        gen_ids = [g.id for g in gens]

        stocks_res = await db.execute(select(FuelStock).where(FuelStock.facility_id == facility_id))
        stocks = stocks_res.scalars().all()
        stock_ids = [s.id for s in stocks]

        if gen_ids:
            await db.execute(delete(GeneratorRun).where(GeneratorRun.generator_id.in_(gen_ids)))
            await db.execute(delete(MaintenanceRecord).where(MaintenanceRecord.generator_id.in_(gen_ids)))
            await db.execute(delete(Fault).where(Fault.generator_id.in_(gen_ids)))
            await db.execute(delete(FuelTransfer).where(FuelTransfer.generator_id.in_(gen_ids)))

            for g in gens:
                g.current_operating_hours = 0.0
                g.fuel_tank_level_l = 0.0
                g.status = "STOPPED"
                g.updated_at = now

            m_res = await db.execute(select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id.in_(gen_ids)))
            for ms in m_res.scalars().all():
                ms.last_performed_hours = 0.0
                ms.next_due_hours = ms.interval_hours

        await db.execute(delete(FuelTransfer).where(FuelTransfer.facility_id == facility_id))
        await db.execute(delete(FuelReceipt).where(FuelReceipt.facility_id == facility_id))
        if stock_ids:
            await db.execute(delete(FuelReceipt).where(FuelReceipt.stock_id.in_(stock_ids)))
            for s in stocks:
                s.current_balance_l = 0.0
                s.updated_at = now

        await log_audit(
            db=db,
            action="SYSTEM_FACILITY_CLEAN",
            entity_type="Facility",
            entity_id=str(facility_id),
            user_id=user_id,
            details={"mode": mode, "facility_id": facility_id, "generators_reset": len(gen_ids)},
            ip_address=ip_address
        )
        await db.commit()
        return {"status": "ok", "mode": mode, "message": f"Журнали та лічильники об'єкта #{facility_id} успішно очищено для чистих звітів."}

    elif mode == "reports_clean":
        await db.execute(delete(GeneratorRun))
        await db.execute(delete(FuelTransfer))
        await db.execute(delete(FuelReceipt))
        await db.execute(delete(MaintenanceRecord))
        await db.execute(delete(Fault))
        await db.execute(delete(SystemAdjustment))
        await db.execute(delete(AuditLog))

        await db.execute(update(Generator).values(
            current_operating_hours=0.0,
            fuel_tank_level_l=0.0,
            status="STOPPED",
            updated_at=now
        ))
        await db.execute(update(FuelStock).values(
            current_balance_l=0.0,
            updated_at=now
        ))
        m_res = await db.execute(select(MaintenanceSchedule))
        for ms in m_res.scalars().all():
            ms.last_performed_hours = 0.0
            ms.next_due_hours = ms.interval_hours

        await log_audit(
            db=db,
            action="SYSTEM_REPORTS_CLEAN",
            entity_type="System",
            entity_id="all",
            user_id=user_id,
            details={"mode": mode, "description": "Повне очищення експлуатаційних журналів і лічильників для чистих звітів"},
            ip_address=ip_address
        )
        await db.commit()
        return {"status": "ok", "mode": mode, "message": "Усі експлуатаційні журнали, історія та лічильники очищено. Звіти чисті."}

    elif mode == "settings_reset":
        await db.execute(delete(SystemSetting))
        await db.commit()
        RUNTIME_SETTINGS.clear()
        RUNTIME_SETTINGS.update(DEFAULT_SYSTEM_SETTINGS)
        await load_system_settings(db)
        await log_audit(
            db=db,
            action="SYSTEM_SETTINGS_RESET",
            entity_type="SystemSetting",
            entity_id="all",
            user_id=user_id,
            details={"mode": mode},
            ip_address=ip_address
        )
        await db.commit()
        return {"status": "ok", "mode": mode, "message": "Системні налаштування скинуто до заводських значень."}

    elif mode == "factory_reset":
        # Complete wipe of operational & structural data except superadmin
        await db.execute(delete(GeneratorRun))
        await db.execute(delete(FuelTransfer))
        await db.execute(delete(FuelReceipt))
        await db.execute(delete(MaintenanceRecord))
        await db.execute(delete(MaintenanceSchedule))
        await db.execute(delete(Fault))
        await db.execute(delete(GeneratorSchedule))
        await db.execute(delete(SystemAdjustment))
        await db.execute(delete(AuditLog))
        await db.execute(delete(Generator))
        await db.execute(delete(FuelStock))
        await db.execute(delete(SystemSetting))

        # Remove non-superadmin users
        non_admins_res = await db.execute(select(User).where(User.is_superadmin == False))
        for u in non_admins_res.scalars().all():
            u.roles.clear()
            await db.delete(u)
        await db.flush()

        # Keep or recreate Facility #1
        facs_res = await db.execute(select(Facility))
        for f in facs_res.scalars().all():
            if f.id != 1:
                await db.delete(f)
        await db.flush()

        fac1 = await db.get(Facility, 1)
        if not fac1:
            fac1 = Facility(
                id=1,
                name="Основний об'єкт",
                address="вул. Центральна, 1",
                description="Головна виробничо-офісна локація",
                timezone="Europe/Kyiv",
                created_at=now,
                updated_at=now
            )
            db.add(fac1)
        else:
            fac1.name = "Основний об'єкт"
            fac1.address = "вул. Центральна, 1"
            fac1.description = "Головна виробничо-офісна локація"
            fac1.timezone = "Europe/Kyiv"
            fac1.updated_at = now
        await db.flush()

        # Recreate default FuelStock & default unconfigured Generator
        db.add(FuelStock(
            facility_id=1,
            name="Основний склад ГСМ",
            fuel_type="А-95",
            current_balance_l=0.0,
            updated_at=now
        ))
        db.add(Generator(
            facility_id=1,
            name="Бензиновий генератор 5кВт",
            model="PG-6500",
            manufacturer="PowerGen",
            serial_number="GEN-2026-001",
            rated_power_kw=5.0,
            tank_capacity_l=25.0,
            fuel_type="А-95",
            nominal_consumption_l_per_h=2.2,
            current_operating_hours=0.0,
            fuel_tank_level_l=0.0,
            status="STOPPED",
            is_configured=False,
            timezone="Europe/Kyiv",
            created_at=now,
            updated_at=now
        ))
        await db.flush()

        RUNTIME_SETTINGS.clear()
        RUNTIME_SETTINGS.update(DEFAULT_SYSTEM_SETTINGS)
        await load_system_settings(db)

        await log_audit(
            db=db,
            action="SYSTEM_FACTORY_RESET",
            entity_type="System",
            entity_id="factory",
            user_id=user_id,
            details={"mode": mode, "description": "Повне заводське скидання бази даних (чиста система)"},
            ip_address=ip_address
        )
        await db.commit()
        return {"status": "ok", "mode": mode, "message": "Виконано повне заводське скидання БД. Система повністю чиста і готова до роботи або передачі замовнику."}

    else:
        raise ValueError(f"Невідомий режим очищення: {mode}")

