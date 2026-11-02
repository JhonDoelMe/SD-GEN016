import json
import re
import gzip
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

# Default WOG Ukraine retail fuel prices fallback (UAH per liter)
DEFAULT_INTERNET_PRICES: Dict[str, float] = {
    "А-95": 92.90,
    "А-95 Mustang": 95.90,
    "А-100 Mustang": 102.90,
    "А-92": 92.90,
    "ДП": 103.50,
    "ДП Mustang+": 106.50,
    "ГАЗ": 52.50,
    "AdBlue": 61.90,
}

DEFAULT_WOG_LINEUP = [
    {"type": "ДП", "brand": "Євро5", "label": "ДП Євро5", "price": 103.50},
    {"type": "ДП", "brand": "Mustang+", "label": "ДП Mustang+", "price": 106.50},
    {"type": "95", "brand": "Євро5-Е10", "label": "95 Євро5-Е10", "price": 92.90},
    {"type": "95", "brand": "Mustang Євро5-Е10", "label": "95 Mustang Євро5-Е10", "price": 95.90},
    {"type": "100", "brand": "Mustang Євро5-Е0", "label": "100 Mustang Євро5-Е0", "price": 102.90},
    {"type": "ГАЗ", "brand": "", "label": "ГАЗ", "price": 52.50},
    {"type": "AdBlue", "brand": "", "label": "AdBlue", "price": 61.90},
]

# Default OKKO Ukraine retail fuel prices fallback (UAH per liter)
DEFAULT_OKKO_PRICES: Dict[str, float] = {
    "А-95": 92.90,
    "А-95 Pulls": 95.90,
    "А-100 Pulls": 102.90,
    "А-92": 92.90,
    "ДП": 106.90,
    "ДП Pulls": 109.90,
    "ГАЗ": 59.90,
    "AdBlue": 61.90,
}

DEFAULT_OKKO_LINEUP = [
    {"type": "ДП", "brand": "Євро", "label": "ДП Євро", "price": 106.90},
    {"type": "ДП", "brand": "Pulls", "label": "Pulls Дизель", "price": 109.90},
    {"type": "95", "brand": "Євро", "label": "А-95 Євро", "price": 92.90},
    {"type": "95", "brand": "Pulls", "label": "Pulls 95", "price": 95.90},
    {"type": "100", "brand": "Pulls", "label": "Pulls 100", "price": 102.90},
    {"type": "ГАЗ", "brand": "СПБТ", "label": "ГАЗ (СПБТ)", "price": 59.90},
    {"type": "AdBlue", "brand": "", "label": "AdBlue", "price": 61.90},
]

# Default dynamic system settings (stored in DB table `system_settings`)
DEFAULT_SYSTEM_SETTINGS: Dict[str, Any] = {
    "organization_name": "MAXI-UA LLC",
    "facility_timezone": "Europe/Kyiv",
    "work_schedule_start": "08:00",
    "work_schedule_end": "20:00",
    "enforce_work_schedule": True,
    "apply_to_all_generators": True,
    "default_maintenance_interval_hours": 300.0,
    "login_max_attempts": 5,
    "login_lockout_seconds": 300,
    # Fuel pricing configuration (0.0 means "not manually set -> use WOG internet price")
    "fuel_price_a95": 0.0,
    "fuel_price_a92": 0.0,
    "fuel_price_dp": 0.0,
    "auto_fetch_fuel_prices": True,
    # Cached WOG internet prices
    "internet_price_a95": DEFAULT_INTERNET_PRICES["А-95"],
    "internet_price_a95_mustang": DEFAULT_INTERNET_PRICES["А-95 Mustang"],
    "internet_price_a100_mustang": DEFAULT_INTERNET_PRICES["А-100 Mustang"],
    "internet_price_a92": DEFAULT_INTERNET_PRICES["А-92"],
    "internet_price_dp": DEFAULT_INTERNET_PRICES["ДП"],
    "internet_price_dp_mustang": DEFAULT_INTERNET_PRICES["ДП Mustang+"],
    "internet_price_gas": DEFAULT_INTERNET_PRICES["ГАЗ"],
    "internet_price_adblue": DEFAULT_INTERNET_PRICES["AdBlue"],
    "wog_lineup": DEFAULT_WOG_LINEUP,
    "internet_prices_updated_at": "",
    "internet_prices_source": "АЗК WOG (https://wog.ua/ua/fuels/)",
    # Cached OKKO internet prices
    "okko_price_a95": DEFAULT_OKKO_PRICES["А-95"],
    "okko_price_a95_pulls": DEFAULT_OKKO_PRICES["А-95 Pulls"],
    "okko_price_a100_pulls": DEFAULT_OKKO_PRICES["А-100 Pulls"],
    "okko_price_a92": DEFAULT_OKKO_PRICES["А-92"],
    "okko_price_dp": DEFAULT_OKKO_PRICES["ДП"],
    "okko_price_dp_pulls": DEFAULT_OKKO_PRICES["ДП Pulls"],
    "okko_price_gas": DEFAULT_OKKO_PRICES["ГАЗ"],
    "okko_price_adblue": DEFAULT_OKKO_PRICES["AdBlue"],
    "okko_lineup": DEFAULT_OKKO_LINEUP,
    "okko_prices_updated_at": "",
    "okko_prices_source": "АЗК OKKO (https://www.okko.ua/fuels)",
    # Push Notifications configuration
    "notifications_enabled": True,
    "notify_generator_start": True,
    "notify_generator_stop": True,
    "notify_low_fuel": True,
    "low_fuel_threshold_l": 5.0,
    "notify_maintenance": True,
    "max_maintenance_notifications_per_day": 2,
    "notify_critical_faults": True,
    "vapid_claims_sub": "mailto:maxiuallc@gmail.com",
    # Automated Backups configuration
    "backup_auto_enabled": False,
    "backup_schedule_time": "03:00",
    "backup_frequency": "daily",
    "backup_retention_count": 7,
    "backup_default_type": "full",
    "backup_last_auto_run_date": "",
    # Operational Safeguards ("Запобіжники")
    "max_continuous_run_hours": 12.0,
    "auto_stop_on_schedule_end": True,
    "notify_running_heartbeat": True,
    "heartbeat_interval_hours": 4.0,
    "fuel_receipt_max_liters_warning": 1000.0,
    "fuel_receipt_min_price": 15.0,
    "fuel_receipt_max_price": 250.0,
    # SMTP Email System & Failover Configuration
    "smtp_enabled": False,
    "smtp_primary_host": "smtp.gmail.com",
    "smtp_primary_port": 587,
    "smtp_primary_user": "",
    "smtp_primary_password": "",
    "smtp_primary_ssl": False,
    "smtp_primary_from": "",
    "smtp_fallback_enabled": False,
    "smtp_fallback_host": "smtp.ukr.net",
    "smtp_fallback_port": 465,
    "smtp_fallback_user": "",
    "smtp_fallback_password": "",
    "smtp_fallback_ssl": True,
    "smtp_fallback_from": "",
    # Email Notification Event Triggers
    "email_notify_password_change": True,
    "email_notify_safety_stop": True,
    "email_notify_critical_fault": True,
    "email_notify_maintenance_due": True,
    "email_weekly_report_enabled": False,
    "email_weekly_recipients": "",
    "email_weekly_send_day": 0,
    "email_weekly_send_time": "08:00",
    "last_weekly_digest_date": "",
    # Default Facility, Generator & Fuel Stock Chain (Fixed Binding)
    "default_facility_id": None,
    "default_generator_id": None,
    "default_fuel_stock_id": None,
    "email_weekly_facility_id": None,
    "email_weekly_generator_id": None,
}

# In-memory cache of runtime settings for fast synchronous reads (e.g. timezone.py)
RUNTIME_SETTINGS: Dict[str, Any] = dict(DEFAULT_SYSTEM_SETTINGS)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?$")


def get_runtime_setting(key: str, default: Any = None) -> Any:
    return RUNTIME_SETTINGS.get(key, DEFAULT_SYSTEM_SETTINGS.get(key, default))


def set_runtime_setting(key: str, value: Any) -> None:
    RUNTIME_SETTINGS[key] = value


def get_runtime_timezone() -> str:
    tz = str(RUNTIME_SETTINGS.get("facility_timezone") or "Europe/Kyiv").strip()
    try:
        ZoneInfo(tz)
        return tz
    except Exception:
        return "Europe/Kyiv"


def fetch_wog_fuel_prices_online(timeout: float = 6.0) -> Tuple[Dict[str, float], list, str, bool]:
    """
    Парсить офіційні актуальні ціни на пальне з сайту АЗК WOG:
    https://wog.ua/ua/fuels/
    Повертає: (prices_dict, wog_lineup_list, source_label, is_live_from_internet)
    """
    prices = dict(DEFAULT_INTERNET_PRICES)
    lineup = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        req = urllib.request.Request("https://wog.ua/ua/fuels/", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Method 1: Parse WOG Next.js SSR JSON blocks ("i_am_page_element":"block.fuels_fuel")
        json_matches = list(re.finditer(
            r'"price"\s*:\s*(\d+)\s*,\s*"cla"\s*:\s*"[^"]*"\s*,\s*"i_am_page_element"\s*:\s*"block\.fuels_fuel"\s*,\s*"type"\s*:\s*"([^"]*)"\s*,\s*"brand"\s*:\s*"([^"]*)"',
            html
        ))
        for m in json_matches:
            raw_kop = int(m.group(1))
            f_type = m.group(2).strip()
            f_brand = m.group(3).strip()
            val_uah = round(raw_kop / 100.0, 2)
            if 10.0 <= val_uah <= 300.0:
                label = f"{f_type} {f_brand}".strip()
                lineup.append({"type": f_type, "brand": f_brand, "label": label, "price": val_uah})

        # Method 2: Fallback to HTML blocks on https://wog.ua/ua/fuels/ if JSON layout changes
        if not lineup:
            html_matches = list(re.finditer(
                r'<div class="s_type__[^"]*">([^<]*)</div><div class="s_brand__[^"]*">([^<]*)</div></div><div class="s_price__[^"]*">([0-9]+(?:[.,][0-9]+)?)</div>',
                html
            ))
            for m in html_matches:
                f_type = m.group(1).strip()
                f_brand = m.group(2).strip()
                val_uah = round(float(m.group(3).replace(",", ".")), 2)
                if 10.0 <= val_uah <= 300.0:
                    label = f"{f_type} {f_brand}".strip()
                    lineup.append({"type": f_type, "brand": f_brand, "label": label, "price": val_uah})

        if lineup:
            for item in lineup:
                ft = item["type"].upper()
                fb = item["brand"].upper()
                p = item["price"]
                if ft == "95":
                    if "MUSTANG" in fb:
                        prices["А-95 Mustang"] = p
                    else:
                        prices["А-95"] = p
                        # WOG no longer sells А-92; sync А-92 fallback to standard WOG 95 Euro5
                        prices["А-92"] = p
                elif ft == "ДП":
                    if "MUSTANG" in fb:
                        prices["ДП Mustang+"] = p
                    else:
                        prices["ДП"] = p
                elif "ГАЗ" in ft:
                    prices["ГАЗ"] = p
                elif ft == "92" or "92" in fb:
                    prices["А-92"] = p

            return prices, lineup, "АЗК WOG (wog.ua/ua/fuels)", True
    except Exception:
        pass

    return prices, list(DEFAULT_WOG_LINEUP), "АЗК WOG (резервний кеш)", False


# Backward compatibility alias
fetch_ukraine_fuel_prices_online = fetch_wog_fuel_prices_online


def fetch_okko_fuel_prices_online(timeout: float = 6.0) -> Tuple[Dict[str, float], list, str, bool]:
    """
    Парсить офіційні актуальні ціни на пальне з сайту АЗК OKKO:
    https://www.okko.ua/fuels
    Повертає: (prices_dict, okko_lineup_list, source_label, is_live_from_internet)
    """
    prices = dict(DEFAULT_OKKO_PRICES)
    lineup = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
    }
    try:
        req = urllib.request.Request("https://www.okko.ua/fuels", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            html = data.decode("utf-8", errors="ignore")

        # Method 1: Extract prices from bullets: { items: [...] } in window.__NUXT__
        bm = re.search(r'bullets\s*:\s*\{items:\s*\[(.*?)\]\}', html)
        if bm:
            b_text = bm.group(1)
            raw_items = re.findall(r'\{[^{}]*?price\s*:\s*["\']([0-9.]+)["\'][^{}]*?\}', b_text)
            if len(raw_items) >= 5:
                p_pulls100 = float(raw_items[0])
                p_pulls_dp = float(raw_items[1])
                p_dp_euro = float(raw_items[2])
                p_pulls95 = float(raw_items[3])
                p_a95_euro = float(raw_items[4])
                p_gas = float(raw_items[5]) if len(raw_items) > 5 else DEFAULT_OKKO_PRICES["ГАЗ"]
                p_adblue = float(raw_items[6]) if len(raw_items) > 6 else DEFAULT_OKKO_PRICES["AdBlue"]

                prices["А-100 Pulls"] = p_pulls100
                prices["ДП Pulls"] = p_pulls_dp
                prices["ДП"] = p_dp_euro
                prices["А-95 Pulls"] = p_pulls95
                prices["А-95"] = p_a95_euro
                prices["А-92"] = p_a95_euro
                prices["ГАЗ"] = p_gas
                prices["AdBlue"] = p_adblue

                lineup = [
                    {"type": "ДП", "brand": "Євро", "label": "ДП Євро", "price": p_dp_euro},
                    {"type": "ДП", "brand": "Pulls", "label": "Pulls Дизель", "price": p_pulls_dp},
                    {"type": "95", "brand": "Євро", "label": "А-95 Євро", "price": p_a95_euro},
                    {"type": "95", "brand": "Pulls", "label": "Pulls 95", "price": p_pulls95},
                    {"type": "100", "brand": "Pulls", "label": "Pulls 100", "price": p_pulls100},
                    {"type": "ГАЗ", "brand": "СПБТ", "label": "ГАЗ (СПБТ)", "price": p_gas},
                    {"type": "AdBlue", "brand": "", "label": "AdBlue", "price": p_adblue},
                ]
                return prices, lineup, "АЗК OKKO (okko.ua/fuels)", True

        # Method 2: Fallback to rendered DOM elements if Nuxt SSR layout differs
        dom_prices = re.findall(r'class="price"[^>]*>\s*(\d+)\s*<sup[^>]*>(\d+)</sup>\s*</span>', html)
        if len(dom_prices) >= 5:
            p_pulls100 = float(f"{dom_prices[0][0]}.{dom_prices[0][1]}")
            p_pulls_dp = float(f"{dom_prices[1][0]}.{dom_prices[1][1]}")
            p_dp_euro = float(f"{dom_prices[2][0]}.{dom_prices[2][1]}")
            p_pulls95 = float(f"{dom_prices[3][0]}.{dom_prices[3][1]}")
            p_a95_euro = float(f"{dom_prices[4][0]}.{dom_prices[4][1]}")
            p_gas = float(f"{dom_prices[5][0]}.{dom_prices[5][1]}") if len(dom_prices) > 5 else DEFAULT_OKKO_PRICES["ГАЗ"]
            p_adblue = float(f"{dom_prices[6][0]}.{dom_prices[6][1]}") if len(dom_prices) > 6 else DEFAULT_OKKO_PRICES["AdBlue"]

            prices["А-100 Pulls"] = p_pulls100
            prices["ДП Pulls"] = p_pulls_dp
            prices["ДП"] = p_dp_euro
            prices["А-95 Pulls"] = p_pulls95
            prices["А-95"] = p_a95_euro
            prices["А-92"] = p_a95_euro
            prices["ГАЗ"] = p_gas
            prices["AdBlue"] = p_adblue

            lineup = [
                {"type": "ДП", "brand": "Євро", "label": "ДП Євро", "price": p_dp_euro},
                {"type": "ДП", "brand": "Pulls", "label": "Pulls Дизель", "price": p_pulls_dp},
                {"type": "95", "brand": "Євро", "label": "А-95 Євро", "price": p_a95_euro},
                {"type": "95", "brand": "Pulls", "label": "Pulls 95", "price": p_pulls95},
                {"type": "100", "brand": "Pulls", "label": "Pulls 100", "price": p_pulls100},
                {"type": "ГАЗ", "brand": "СПБТ", "label": "ГАЗ (СПБТ)", "price": p_gas},
                {"type": "AdBlue", "brand": "", "label": "AdBlue", "price": p_adblue},
            ]
            return prices, lineup, "АЗК OKKO (okko.ua/fuels)", True
    except Exception:
        pass

    return prices, list(DEFAULT_OKKO_LINEUP), "АЗК OKKO (резервний кеш)", False


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

    # Авто-міграція старих не-WOG кешованих інтернет-цін на актуальне табло АЗК WOG
    if "WOG" not in str(merged.get("internet_prices_source") or "").upper():
        wog_keys = (
            "internet_price_a95",
            "internet_price_a95_mustang",
            "internet_price_a100_mustang",
            "internet_price_a92",
            "internet_price_dp",
            "internet_price_dp_mustang",
            "internet_price_gas",
            "internet_price_adblue",
            "wog_lineup",
            "internet_prices_source",
        )
        for wk in wog_keys:
            if wk in DEFAULT_SYSTEM_SETTINGS:
                merged[wk] = DEFAULT_SYSTEM_SETTINGS[wk]
                if wk in existing_map:
                    existing_map[wk].value_json = json.dumps(DEFAULT_SYSTEM_SETTINGS[wk], ensure_ascii=False)
                    needs_flush = True

    if needs_flush:
        await db.commit()

    RUNTIME_SETTINGS.update(merged)
    return dict(RUNTIME_SETTINGS)


async def update_system_settings(
    db: AsyncSession,
    updates: Dict[str, Any],
    apply_to_all_generators: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Оновлює системні налаштування в БД та в RUNTIME_SETTINGS.
    Опціонально синхронізує часовий пояс та робочий графік для всіх об'єктів та генераторів.
    """
    await load_system_settings(db)

    if apply_to_all_generators is not None:
        updates["apply_to_all_generators"] = bool(apply_to_all_generators)

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
    for time_key in ("work_schedule_start", "work_schedule_end", "email_weekly_send_time"):
        if time_key in updates and updates[time_key] is not None:
            t_val = str(updates[time_key]).strip()
            m = _TIME_RE.match(t_val)
            if not m:
                raise ValueError(f"Некоректний формат часу '{t_val}' для {time_key} (очікується ГГ:ХХ)")
            # Always normalize to HH:MM format
            updates[time_key] = f"{m.group(1)}:{m.group(2)}"

    # Validate Default Facility, Generator & Fuel Stock chain binding (Domain Integrity)
    chain_keys = {"default_facility_id", "default_generator_id", "default_fuel_stock_id"}
    if chain_keys.intersection(updates.keys()):
        target_fac_id = updates["default_facility_id"] if "default_facility_id" in updates else RUNTIME_SETTINGS.get("default_facility_id")
        target_gen_id = updates["default_generator_id"] if "default_generator_id" in updates else RUNTIME_SETTINGS.get("default_generator_id")
        target_stock_id = updates["default_fuel_stock_id"] if "default_fuel_stock_id" in updates else RUNTIME_SETTINGS.get("default_fuel_stock_id")

        if target_fac_id is not None:
            fac = await db.get(Facility, target_fac_id)
            if not fac:
                raise ValueError(f"Об'єкт за замовчуванням з ID {target_fac_id} не знайдено в системі")

            if target_gen_id is not None:
                gen = await db.get(Generator, target_gen_id)
                if not gen:
                    raise ValueError(f"Генератор за замовчуванням з ID {target_gen_id} не знайдено в системі")
                if gen.facility_id is None:
                    raise ValueError(
                        f"Генератор '{gen.name}' (ID {gen.id}) не закріплений за жодним об'єктом "
                        f"і не може бути генератором за замовчуванням для об'єкта ID {target_fac_id}"
                    )
                if int(gen.facility_id) != int(target_fac_id):
                    raise ValueError(
                        f"Генератор '{gen.name}' закріплений за об'єктом ID {gen.facility_id}, "
                        f"а не за вказаним об'єктом за замовчуванням ID {target_fac_id}"
                    )

            if target_stock_id is not None:
                stock = await db.get(FuelStock, target_stock_id)
                if not stock:
                    raise ValueError(f"Склад ГСМ за замовчуванням з ID {target_stock_id} не знайдено в системі")
                if stock.facility_id is None:
                    raise ValueError(
                        f"Склад ГСМ '{stock.name}' (ID {stock.id}) не закріплений за жодним об'єктом "
                        f"і не може бути складом за замовчуванням для об'єкта ID {target_fac_id}"
                    )
                if int(stock.facility_id) != int(target_fac_id):
                    raise ValueError(
                        f"Склад ГСМ '{stock.name}' закріплений за об'єктом ID {stock.facility_id}, "
                        f"а не за вказаним об'єктом за замовчуванням ID {target_fac_id}"
                    )
        else:
            if target_gen_id is not None or target_stock_id is not None:
                raise ValueError("Неможливо встановити генератор або склад за замовчуванням без визначення об'єкта за замовчуванням")

    # Validate Weekly Email Report chain
    weekly_keys = {"email_weekly_facility_id", "email_weekly_generator_id"}
    if weekly_keys.intersection(updates.keys()):
        w_fac_id = updates["email_weekly_facility_id"] if "email_weekly_facility_id" in updates else RUNTIME_SETTINGS.get("email_weekly_facility_id")
        w_gen_id = updates["email_weekly_generator_id"] if "email_weekly_generator_id" in updates else RUNTIME_SETTINGS.get("email_weekly_generator_id")

        if w_fac_id is not None:
            fac = await db.get(Facility, w_fac_id)
            if not fac:
                raise ValueError(f"Об'єкт для щотижневого звіту з ID {w_fac_id} не знайдено в системі")

            if w_gen_id is not None:
                gen = await db.get(Generator, w_gen_id)
                if not gen:
                    raise ValueError(f"Генератор для щотижневого звіту з ID {w_gen_id} не знайдено в системі")
                if gen.facility_id is None:
                    raise ValueError(
                        f"Генератор для щотижневого звіту '{gen.name}' не закріплений за жодним об'єктом "
                        f"і не може бути призначений для об'єкта звіту ID {w_fac_id}"
                    )
                if int(gen.facility_id) != int(w_fac_id):
                    raise ValueError(
                        f"Генератор для щотижневого звіту '{gen.name}' закріплений за об'єктом ID {gen.facility_id}, "
                        f"а не за вказаним об'єктом звіту ID {w_fac_id}"
                    )
        else:
            if w_gen_id is not None:
                raise ValueError("Неможливо призначити генератор для щотижневого звіту без визначення об'єкта звіту")

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    # Collect valid updates into pending dict to guarantee atomic in-memory publish only after successful commit
    pending_updates: Dict[str, Any] = {}
    for k, val in updates.items():
        if k not in DEFAULT_SYSTEM_SETTINGS:
            continue
        pending_updates[k] = val
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

    if apply_to_all_generators or updates.get("apply_to_all_generators"):
        tz = pending_updates.get("facility_timezone", RUNTIME_SETTINGS.get("facility_timezone", "Europe/Kyiv"))
        w_start = pending_updates.get("work_schedule_start", RUNTIME_SETTINGS.get("work_schedule_start", "08:00"))
        w_end = pending_updates.get("work_schedule_end", RUNTIME_SETTINGS.get("work_schedule_end", "20:00"))
        maint_int = float(pending_updates.get("default_maintenance_interval_hours", RUNTIME_SETTINGS.get("default_maintenance_interval_hours", 300.0)))

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

    try:
        await db.commit()
    except Exception as db_err:
        await db.rollback()
        raise db_err

    # Atomic publish to in-memory runtime cache strictly AFTER successful commit
    RUNTIME_SETTINGS.update(pending_updates)
    return dict(RUNTIME_SETTINGS)


async def refresh_internet_fuel_prices(db: AsyncSession, provider: str = "all") -> Dict[str, Any]:
    """
    Запитує актуальні ціни на пальне з офіційного сайту АЗК WOG (https://wog.ua/ua/fuels/)
    та/або АЗК OKKO (https://www.okko.ua/fuels) та зберігає їх у SystemSetting.
    provider: 'wog' | 'okko' | 'all'
    """
    now_str = datetime.datetime.now(ZoneInfo(get_runtime_timezone())).strftime("%Y-%m-%d %H:%M:%S")
    updates: Dict[str, Any] = {}
    p_norm = (provider or "all").lower().strip()

    if p_norm in ("wog", "all"):
        prices_wog, lineup_wog, source_wog, is_live_wog = fetch_wog_fuel_prices_online()
        updates.update({
            "internet_price_a95": prices_wog.get("А-95", DEFAULT_INTERNET_PRICES["А-95"]),
            "internet_price_a95_mustang": prices_wog.get("А-95 Mustang", DEFAULT_INTERNET_PRICES["А-95 Mustang"]),
            "internet_price_a100_mustang": prices_wog.get("А-100 Mustang", DEFAULT_INTERNET_PRICES["А-100 Mustang"]),
            "internet_price_a92": prices_wog.get("А-92", DEFAULT_INTERNET_PRICES["А-92"]),
            "internet_price_dp": prices_wog.get("ДП", DEFAULT_INTERNET_PRICES["ДП"]),
            "internet_price_dp_mustang": prices_wog.get("ДП Mustang+", DEFAULT_INTERNET_PRICES["ДП Mustang+"]),
            "internet_price_gas": prices_wog.get("ГАЗ", DEFAULT_INTERNET_PRICES["ГАЗ"]),
            "internet_price_adblue": prices_wog.get("AdBlue", DEFAULT_INTERNET_PRICES["AdBlue"]),
            "wog_lineup": lineup_wog,
            "internet_prices_updated_at": now_str,
            "internet_prices_source": source_wog,
        })

    if p_norm in ("okko", "all"):
        prices_okko, lineup_okko, source_okko, is_live_okko = fetch_okko_fuel_prices_online()
        updates.update({
            "okko_price_a95": prices_okko.get("А-95", DEFAULT_OKKO_PRICES["А-95"]),
            "okko_price_a95_pulls": prices_okko.get("А-95 Pulls", DEFAULT_OKKO_PRICES["А-95 Pulls"]),
            "okko_price_a100_pulls": prices_okko.get("А-100 Pulls", DEFAULT_OKKO_PRICES["А-100 Pulls"]),
            "okko_price_a92": prices_okko.get("А-92", DEFAULT_OKKO_PRICES["А-92"]),
            "okko_price_dp": prices_okko.get("ДП", DEFAULT_OKKO_PRICES["ДП"]),
            "okko_price_dp_pulls": prices_okko.get("ДП Pulls", DEFAULT_OKKO_PRICES["ДП Pulls"]),
            "okko_price_gas": prices_okko.get("ГАЗ", DEFAULT_OKKO_PRICES["ГАЗ"]),
            "okko_price_adblue": prices_okko.get("AdBlue", DEFAULT_OKKO_PRICES["AdBlue"]),
            "okko_lineup": lineup_okko,
            "okko_prices_updated_at": now_str,
            "okko_prices_source": source_okko,
        })

    if updates:
        await update_system_settings(db, updates)
    return get_fuel_prices_info()


def get_fuel_prices_info() -> Dict[str, Any]:
    """
    Повертає повну інформацію про ціни на пальне:
    налаштовані вручну, ціни з мережі WOG (https://wog.ua/ua/fuels/) та OKKO (https://www.okko.ua/fuels),
    а також діючі ціни для розрахунку.
    """
    mapping_wog = [
        ("А-95", "fuel_price_a95", "internet_price_a95"),
        ("А-95 Mustang", "fuel_price_a95", "internet_price_a95_mustang"),
        ("ДП", "fuel_price_dp", "internet_price_dp"),
        ("ДП Mustang+", "fuel_price_dp", "internet_price_dp_mustang"),
        ("ГАЗ", "fuel_price_a92", "internet_price_gas"),
        ("А-92", "fuel_price_a92", "internet_price_a92"),
    ]
    fuels: Dict[str, Dict[str, Any]] = {}
    for label, conf_key, net_key in mapping_wog:
        conf_val = float(RUNTIME_SETTINGS.get(conf_key) or 0.0)
        net_val = float(RUNTIME_SETTINGS.get(net_key) or DEFAULT_INTERNET_PRICES.get(label, 92.90))
        if conf_val > 0 and label in ("А-95", "ДП", "А-92"):
            effective = round(conf_val, 2)
            source = "settings"
            source_name = "Встановлено в налаштуваннях"
        else:
            effective = round(net_val, 2)
            source = "internet"
            source_name = str(RUNTIME_SETTINGS.get("internet_prices_source") or "АЗК WOG (wog.ua/ua/fuels/)")

        fuels[label] = {
            "fuel_type": label,
            "effective_price": effective,
            "configured_price": round(conf_val, 2) if label in ("А-95", "ДП", "А-92") else 0.0,
            "internet_price": round(net_val, 2),
            "source": source,
            "source_name": source_name,
        }

    mapping_okko = [
        ("А-95", "fuel_price_a95", "okko_price_a95"),
        ("А-95 Pulls", "fuel_price_a95", "okko_price_a95_pulls"),
        ("ДП", "fuel_price_dp", "okko_price_dp"),
        ("ДП Pulls", "fuel_price_dp", "okko_price_dp_pulls"),
        ("А-100 Pulls", None, "okko_price_a100_pulls"),
        ("ГАЗ", "fuel_price_a92", "okko_price_gas"),
        ("А-92", "fuel_price_a92", "okko_price_a92"),
    ]
    okko_fuels: Dict[str, Dict[str, Any]] = {}
    for label, conf_key, net_key in mapping_okko:
        conf_val = float(RUNTIME_SETTINGS.get(conf_key) or 0.0) if conf_key else 0.0
        net_val = float(RUNTIME_SETTINGS.get(net_key) or DEFAULT_OKKO_PRICES.get(label, 92.90))
        if conf_val > 0 and label in ("А-95", "ДП", "А-92"):
            effective = round(conf_val, 2)
            source = "settings"
            source_name = "Встановлено в налаштуваннях"
        else:
            effective = round(net_val, 2)
            source = "internet"
            source_name = str(RUNTIME_SETTINGS.get("okko_prices_source") or "АЗК OKKO (okko.ua/fuels)")

        okko_fuels[label] = {
            "fuel_type": label,
            "effective_price": effective,
            "configured_price": round(conf_val, 2) if label in ("А-95", "ДП", "А-92") else 0.0,
            "internet_price": round(net_val, 2),
            "source": source,
            "source_name": source_name,
        }

    return {
        "fuels": fuels,
        "okko_fuels": okko_fuels,
        "wog_lineup": RUNTIME_SETTINGS.get("wog_lineup") or list(DEFAULT_WOG_LINEUP),
        "okko_lineup": RUNTIME_SETTINGS.get("okko_lineup") or list(DEFAULT_OKKO_LINEUP),
        "auto_fetch_fuel_prices": bool(RUNTIME_SETTINGS.get("auto_fetch_fuel_prices", True)),
        "internet_prices_updated_at": RUNTIME_SETTINGS.get("internet_prices_updated_at") or "",
        "internet_prices_source": RUNTIME_SETTINGS.get("internet_prices_source") or "АЗК WOG (wog.ua/ua/fuels/)",
        "okko_prices_updated_at": RUNTIME_SETTINGS.get("okko_prices_updated_at") or "",
        "okko_prices_source": RUNTIME_SETTINGS.get("okko_prices_source") or "АЗК OKKO (https://www.okko.ua/fuels)",
    }


async def resolve_fuel_price_per_liter(
    db: AsyncSession,
    fuel_type: str,
    provider: str = "wog"
) -> Tuple[float, str]:
    """
    Визначає ціну за літр для оприбуткування палива, якщо сума чека не була вказана:
    1) Якщо в налаштуваннях задана власна ціна > 0 для базового типу палива -> використовує її.
    2) Інакше використовує актуальну ціну з обраної мережі АЗК (WOG або OKKO).
    """
    await load_system_settings(db)
    ft = (fuel_type or "А-95").strip().upper()
    prov = (provider or "wog").strip().lower()

    is_premium = "MUSTANG" in ft or "PULLS" in ft or "+" in ft
    is_okko = "okko" in prov

    if is_okko:
        if "100" in ft:
            norm_ft = "А-100 Pulls"
            conf_key = None
            net_key = "okko_price_a100_pulls"
            fallback_val = DEFAULT_OKKO_PRICES["А-100 Pulls"]
        elif "ГАЗ" in ft or "LPG" in ft or "GAS" in ft or "СПБТ" in ft:
            norm_ft = "ГАЗ"
            conf_key = None
            net_key = "okko_price_gas"
            fallback_val = DEFAULT_OKKO_PRICES["ГАЗ"]
        elif "ADBLUE" in ft:
            norm_ft = "AdBlue"
            conf_key = None
            net_key = "okko_price_adblue"
            fallback_val = DEFAULT_OKKO_PRICES["AdBlue"]
        elif "92" in ft:
            norm_ft = "А-92"
            conf_key = "fuel_price_a92"
            net_key = "okko_price_a92"
            fallback_val = DEFAULT_OKKO_PRICES["А-92"]
        elif "ДП" in ft or "ДИЗ" in ft or "DIESEL" in ft:
            if is_premium:
                norm_ft = "ДП Pulls"
                conf_key = None
                net_key = "okko_price_dp_pulls"
                fallback_val = DEFAULT_OKKO_PRICES["ДП Pulls"]
            else:
                norm_ft = "ДП"
                conf_key = "fuel_price_dp"
                net_key = "okko_price_dp"
                fallback_val = DEFAULT_OKKO_PRICES["ДП"]
        else:
            if is_premium:
                norm_ft = "А-95 Pulls"
                conf_key = None
                net_key = "okko_price_a95_pulls"
                fallback_val = DEFAULT_OKKO_PRICES["А-95 Pulls"]
            else:
                norm_ft = "А-95"
                conf_key = "fuel_price_a95"
                net_key = "okko_price_a95"
                fallback_val = DEFAULT_OKKO_PRICES["А-95"]
    else:
        # WOG or default fallback
        if "100" in ft:
            norm_ft = "А-100 Mustang"
            conf_key = None
            net_key = "internet_price_a100_mustang"
            fallback_val = DEFAULT_INTERNET_PRICES["А-100 Mustang"]
        elif "ГАЗ" in ft or "LPG" in ft or "GAS" in ft:
            norm_ft = "ГАЗ"
            conf_key = None
            net_key = "internet_price_gas"
            fallback_val = DEFAULT_INTERNET_PRICES["ГАЗ"]
        elif "ADBLUE" in ft:
            norm_ft = "AdBlue"
            conf_key = None
            net_key = "internet_price_adblue"
            fallback_val = DEFAULT_INTERNET_PRICES["AdBlue"]
        elif "92" in ft:
            norm_ft = "А-92"
            conf_key = "fuel_price_a92"
            net_key = "internet_price_a92"
            fallback_val = DEFAULT_INTERNET_PRICES["А-92"]
        elif "ДП" in ft or "ДИЗ" in ft or "DIESEL" in ft:
            if is_premium:
                norm_ft = "ДП Mustang+"
                conf_key = None
                net_key = "internet_price_dp_mustang"
                fallback_val = DEFAULT_INTERNET_PRICES["ДП Mustang+"]
            else:
                norm_ft = "ДП"
                conf_key = "fuel_price_dp"
                net_key = "internet_price_dp"
                fallback_val = DEFAULT_INTERNET_PRICES["ДП"]
        else:
            if is_premium:
                norm_ft = "А-95 Mustang"
                conf_key = None
                net_key = "internet_price_a95_mustang"
                fallback_val = DEFAULT_INTERNET_PRICES["А-95 Mustang"]
            else:
                norm_ft = "А-95"
                conf_key = "fuel_price_a95"
                net_key = "internet_price_a95"
                fallback_val = DEFAULT_INTERNET_PRICES["А-95"]

    if conf_key:
        conf_price = float(RUNTIME_SETTINGS.get(conf_key) or 0.0)
        if conf_price > 0:
            return round(conf_price, 2), "system_settings"

    # Auto-fetch if not updated
    if RUNTIME_SETTINGS.get("auto_fetch_fuel_prices", True):
        upd_key = "okko_prices_updated_at" if is_okko else "internet_prices_updated_at"
        if not RUNTIME_SETTINGS.get(upd_key):
            try:
                await refresh_internet_fuel_prices(db, provider="okko" if is_okko else "wog")
            except Exception:
                pass

    net_price = float(RUNTIME_SETTINGS.get(net_key) or fallback_val)
    if net_price <= 0:
        net_price = fallback_val

    source_tag = "internet_okko" if is_okko else "internet"
    return round(net_price, 2), source_tag


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
        factory_gen = Generator(
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
            is_configured=True,
            timezone="Europe/Kyiv",
            created_at=now,
            updated_at=now
        )
        db.add(factory_gen)
        await db.flush()

        db.add(GeneratorSchedule(
            generator_id=factory_gen.id,
            weekday=-1,
            start_time="08:00",
            end_time="20:00",
            timezone="Europe/Kyiv",
            is_active=True
        ))
        db.add(MaintenanceSchedule(
            generator_id=factory_gen.id,
            interval_hours=300.0,
            last_performed_hours=0.0,
            next_due_hours=300.0,
            is_active=True
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

