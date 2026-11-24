# -*- coding: utf-8 -*-
import asyncio
import time
import re
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, Tuple, List
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.models.facility import Facility
from backend.app.core.timezone import now_utc, now_facility
from backend.app.services.settings_service import get_effective_str_setting, get_effective_int_setting, get_runtime_timezone

logger = logging.getLogger("sd_gen016.weather")

UA_WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]

METEOALARM_UA_FEED_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-ukraine"
METEOALARM_CACHE_TTL_SEC = 900  # 15 minutes

# In-memory cache: city_key -> (timestamp, weather_dict)
_WEATHER_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
# Feed-level MeteoAlarm cache: (timestamp, parsed_warnings_list)
_METEOALARM_CACHE: Optional[Tuple[float, List[Dict[str, Any]]]] = None
# Deduplication cache for dispatched weather push warnings: (facility_id, signature) -> dispatched_ts
_DISPATCHED_WEATHER_WARNINGS: Dict[Tuple[int, str], float] = {}

# Known coordinates for major Ukrainian cities to avoid extra geocoding calls
KNOWN_COORDINATES: Dict[str, Tuple[float, float]] = {
    "самар": (48.6358, 35.2595),
    "новомосковськ": (48.6358, 35.2595),
    "дніпро": (48.4647, 35.0462),
    "київ": (50.4501, 30.5234),
    "львів": (49.8397, 24.0297),
    "харків": (49.9935, 36.2304),
    "одеса": (46.4825, 30.7233),
    "запоріжжя": (47.8388, 35.1396),
    "кривий ріг": (47.9105, 33.3918),
    "миколаїв": (46.9750, 31.9946),
    "вінниця": (49.2331, 28.4682),
    "полтава": (49.5883, 34.5514),
    "чернігів": (51.4982, 31.2893),
    "черкаси": (49.4444, 32.0598),
    "житомир": (50.2547, 28.6587),
    "суми": (50.9077, 34.7981),
    "хмельницький": (49.4230, 26.9871),
    "чернівці": (48.2921, 25.9358),
    "рівне": (50.6199, 26.2516),
    "івано-франківськ": (48.9226, 24.7111),
    "тернопіль": (49.5535, 25.5948),
    "луцьк": (50.7472, 25.3254),
    "ужгород": (48.6208, 22.2879),
    "нікополь": (47.5760, 34.3980),
    "павлоград": (48.5167, 35.8667),
    "кам'янське": (48.5132, 34.6139),
    "кременчук": (49.0630, 33.4040),
    "біла церква": (49.7989, 30.1153),
    "бровари": (50.5113, 30.7900),
    "бориспіль": (50.3540, 30.9570),
    "ірпінь": (50.5186, 30.2397),
    "буча": (50.5489, 30.2208),
}


def map_icon_to_emoji(icon_code: str) -> str:
    """Конвертує OpenWeather icon код у зрозумілий емодзі для плашки."""
    code = (icon_code or "").lower()
    if code.startswith("01"):
        return "☀️" if "d" in code else "🌙"
    if code.startswith("02"):
        return "⛅"
    if code.startswith("03") or code.startswith("04"):
        return "☁️"
    if code.startswith("09") or code.startswith("10"):
        return "🌧️"
    if code.startswith("11"):
        return "⛈️"
    if code.startswith("13"):
        return "❄️"
    if code.startswith("50"):
        return "🌫️"
    return "⛅"


# Mapping oblast patterns to official Ukrainian oblast names
OBLAST_MAP: Dict[str, str] = {
    "дніпропетровськ": "Дніпропетровська область",
    "київськ": "Київська область",
    "львівськ": "Львівська область",
    "харківськ": "Харківська область",
    "одеськ": "Одеська область",
    "запорізьк": "Запорізька область",
    "миколаївськ": "Миколаївська область",
    "вінницьк": "Вінницька область",
    "полтавськ": "Полтавська область",
    "чернігівськ": "Чернігівська область",
    "черкаськ": "Черкаська область",
    "житомирськ": "Житомирська область",
    "сумськ": "Сумська область",
    "хмельницьк": "Хмельницька область",
    "чернівецьк": "Чернівецька область",
    "рівненськ": "Рівненська область",
    "івано-франківськ": "Івано-Франківська область",
    "тернопільськ": "Тернопільська область",
    "волинськ": "Волинська область",
    "закарпатськ": "Закарпатська область",
    "кіровоградськ": "Кіровоградська область",
    "донецьк": "Донецька область",
    "луганськ": "Луганська область",
    "херсонськ": "Херсонська область",
    "крим": "Автономна Республіка Крим",
}

OBLAST_EN_MAP: Dict[str, Tuple[str, ...]] = {
    "Дніпропетровська область": ("dnipropetrovsk", "дніпропетровськ"),
    "Київська область": ("kyiv oblast", "київській області", "київськ"),
    "м. Київ": ("kyiv", "київ"),
    "Львівська область": ("lviv", "львівськ"),
    "Харківська область": ("kharkiv", "харківськ"),
    "Одеська область": ("odessa", "odesa", "одеськ"),
    "Запорізька область": ("zaporizhia", "zaporizhzhia", "запорізьк"),
    "Миколаївська область": ("mykolaiv", "миколаївськ"),
    "Вінницька область": ("vinnytsia", "вінницьк"),
    "Полтавська область": ("poltava", "полтавськ"),
    "Чернігівська область": ("chernihiv", "чернігівськ"),
    "Черкаська область": ("cherkasy", "черкаськ"),
    "Житомирська область": ("zhytomyr", "житомирськ"),
    "Сумська область": ("sumy", "сумськ"),
    "Хмельницька область": ("khmelnytskyi", "хмельницьк"),
    "Чернівецька область": ("chernivtsi", "чернівецьк"),
    "Рівненська область": ("rivne", "рівненськ"),
    "Івано-Франківська область": ("ivano-frankivsk", "івано-франківськ"),
    "Тернопільська область": ("ternopil", "тернопільськ"),
    "Волинська область": ("volyn", "волинськ"),
    "Закарпатська область": ("zakarpattia", "закарпатськ"),
    "Кіровоградська область": ("kirovohrad", "кіровоградськ"),
    "Донецька область": ("donetsk", "донецьк"),
    "Луганська область": ("luhansk", "луганськ"),
    "Херсонська область": ("kherson", "херсонськ"),
    "Автономна Республіка Крим": ("crimea", "крим"),
}

AWARENESS_TYPE_ICONS: Dict[str, str] = {
    "1": "🌬️",   # wind
    "2": "❄️",    # snow-ice
    "3": "⛈️",   # thunderstorm
    "4": "🌫️",   # fog
    "5": "🌡️",   # high-temperature
    "6": "🥶",   # low-temperature
    "7": "🌊",   # coastal-event
    "8": "🔥",   # forest-fire
    "9": "🏔️",   # avalanches
    "10": "🌧️",  # rain
    "12": "🌊",  # flooding
    "13": "🌊",  # rain-flood
}

CITY_CANONICAL: Dict[str, str] = {
    "самар": "Самар",
    "новомосковськ": "Самар",
    "дніпро": "Дніпро",
    "кривий ріг": "Кривий Ріг",
    "павлоград": "Павлоград",
    "нікополь": "Нікополь",
    "кам'янське": "Кам'янське",
    "київ": "Київ",
    "біла церква": "Біла Церква",
    "бровари": "Бровари",
    "бориспіль": "Бориспіль",
    "ірпінь": "Ірпінь",
    "буча": "Буча",
    "львів": "Львів",
    "харків": "Харків",
    "одеса": "Одеса",
    "запоріжжя": "Запоріжжя",
    "миколаїв": "Миколаїв",
    "вінниця": "Вінниця",
    "полтава": "Полтава",
    "кременчук": "Кременчук",
    "чернігів": "Чернігів",
    "черкаси": "Черкаси",
    "житомир": "Житомир",
    "суми": "Суми",
    "хмельницький": "Хмельницький",
    "чернівці": "Чернівці",
    "рівне": "Рівне",
    "івано-франківськ": "Івано-Франківськ",
    "тернопіль": "Тернопіль",
    "луцьк": "Луцьк",
    "ужгород": "Ужгород",
    "кропивницький": "Кропивницький",
    "херсон": "Херсон",
}

CITY_TO_REGION: Dict[str, str] = {
    "самар": "Дніпропетровська область",
    "новомосковськ": "Дніпропетровська область",
    "дніпро": "Дніпропетровська область",
    "кривий ріг": "Дніпропетровська область",
    "павлоград": "Дніпропетровська область",
    "нікополь": "Дніпропетровська область",
    "кам'янське": "Дніпропетровська область",
    "київ": "м. Київ",
    "біла церква": "Київська область",
    "бровари": "Київська область",
    "бориспіль": "Київська область",
    "ірпінь": "Київська область",
    "буча": "Київська область",
    "львів": "Львівська область",
    "харків": "Харківська область",
    "одеса": "Одеська область",
    "запоріжжя": "Запорізька область",
    "миколаїв": "Миколаївська область",
    "вінниця": "Вінницька область",
    "полтава": "Полтавська область",
    "кременчук": "Полтавська область",
    "чернігів": "Чернігівська область",
    "черкаси": "Черкаська область",
    "житомир": "Житомирська область",
    "суми": "Сумська область",
    "хмельницький": "Хмельницька область",
    "чернівці": "Чернівецька область",
    "рівне": "Рівненська область",
    "івано-франківськ": "Івано-Франківська область",
    "тернопіль": "Тернопільська область",
    "луцьк": "Волинська область",
    "ужгород": "Закарпатська область",
    "кропивницький": "Кіровоградська область",
    "херсон": "Херсонська область",
}


def clean_city_and_region(
    city_raw: Optional[str] = None,
    address_raw: Optional[str] = None,
    name_raw: Optional[str] = None
) -> Tuple[str, str]:
    """
    Очищує та уніфікує назву міста й області для об'єкта,
    усуваючи дублювання та префікси (напр. 'Самар, Дніпропетровська область.' -> ('Самар', 'Дніпропетровська область')).
    """
    all_text = f"{city_raw or ''} {address_raw or ''} {name_raw or ''}"
    lower_all = all_text.lower()

    # 1. Пошук назви області
    detected_region: Optional[str] = None
    for pattern, reg_name in OBLAST_MAP.items():
        if pattern in lower_all:
            detected_region = reg_name
            break

    # 2. Виділення чистого міста
    clean_city: Optional[str] = None
    if city_raw and city_raw.strip():
        city_clean = re.sub(r'^(?:м\.|місто|смт|с\.)\s*', '', city_raw.strip(), flags=re.I)
        city_clean = re.sub(r'[,;].*$', '', city_clean).strip(' .,')

        for k, canon in CITY_CANONICAL.items():
            if re.search(r'\b' + re.escape(k) + r'\b', city_raw.lower()):
                clean_city = canon
                break

        if not clean_city and city_clean:
            if not any(obl in city_clean.lower() for obl in ["область", "обл", "район"]):
                clean_city = city_clean.title()

    if not clean_city:
        for k, canon in CITY_CANONICAL.items():
            if re.search(r'\b' + re.escape(k) + r'\b', lower_all):
                clean_city = canon
                break

    if not clean_city:
        m = re.search(r'(?:м\.|місто|смт)\s*([А-Яа-яІіЇїЄєҐґ\'-]+)', all_text, re.I)
        if m:
            found = m.group(1).strip()
            if not any(obl in found.lower() for obl in ["область", "обл"]):
                clean_city = found.title()

    if not clean_city:
        clean_city = "Київ"

    # 3. Узгодження області
    if not detected_region:
        detected_region = CITY_TO_REGION.get(clean_city.lower())

    if clean_city.lower() == "київ":
        detected_region = "м. Київ"

    if not detected_region:
        detected_region = "Україна"

    return clean_city, detected_region


def clear_weather_cache(city: Optional[str] = None) -> None:
    """Очищує оперативний кеш погоди та попереджень MeteoAlarm."""
    global _WEATHER_CACHE, _METEOALARM_CACHE
    if city:
        _WEATHER_CACHE.pop(f"weather_{city.lower()}", None)
    else:
        _WEATHER_CACHE.clear()
        _METEOALARM_CACHE = None


def extract_city_from_facility(facility: Facility) -> str:
    """Визначає чисту назву міста для об'єкта без дублювання області."""
    clean_c, _ = clean_city_and_region(
        city_raw=getattr(facility, "city", None),
        address_raw=facility.address,
        name_raw=facility.name
    )
    return clean_c


def get_generator_weather_tip(
    temp_c: float,
    humidity: int,
    rain: bool,
    forecast_days: Optional[List[Dict[str, Any]]] = None
) -> str:
    """Формує корисну інженерну пораду для оператора генератора з урахуванням прогнозу на 5 днів."""
    if temp_c < -10.0:
        base_tip = "Сильний мороз! Загусання ДП, перевірте заряд АКБ та підігрів картера перед пуском."
    elif temp_c < 0.0:
        base_tip = "Заморозки: використовуйте зимове ДП. Рекомендується короткий прогрів двигуна (3–5 хв)."
    elif temp_c > 30.0:
        base_tip = "Спека: підвищений ризик перегріву. Контролюйте рівень оливи та вільний приплив повітря."
    elif rain:
        base_tip = "Опади: забезпечте надійне укриття панелі керування та електробезпеку контактів."
    else:
        base_tip = "Оптимальні погодні умови для стабільної експлуатації генератора."

    if forecast_days and temp_c >= 0.0:
        min_future = min((d.get("temp_min_c", temp_c) for d in forecast_days), default=temp_c)
        if min_future < -8.0:
            base_tip += f" Увага: у найближчі дні очікується сильний мороз (до {min_future:.0f}°C) — завчасно підготуйте зимове ДП та АКБ."
        elif min_future < 0.0:
            base_tip += f" Прогноз: у найближчі дні очікуються заморозки (до {min_future:.0f}°C) — перевірте зимове паливо."

    return base_tip


def parse_5day_forecast(forecast_data: Optional[Dict[str, Any]], max_days: int = 5) -> List[Dict[str, Any]]:
    """
    Агрегує 3-годинні інтервали OpenWeather (/data/2.5/forecast) у щоденний прогноз на 5 днів
    (мін/макс температура, денна іконка, опис та ймовірність опадів).
    """
    if not forecast_data or not isinstance(forecast_data, dict):
        return []
    slots = forecast_data.get("list")
    if not slots or not isinstance(slots, list):
        return []

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for item in slots:
        dt_txt = str(item.get("dt_txt") or "")
        if len(dt_txt) < 10:
            continue
        day_str = dt_txt[:10]  # YYYY-MM-DD
        by_date.setdefault(day_str, []).append(item)

    if not by_date:
        return []

    sorted_dates = sorted(by_date.keys())
    today_str = now_facility().strftime("%Y-%m-%d")

    # Якщо для сьогодні залишилось лише 1-2 нічні слоти і попереду є повні 5 днів — показуємо наступні 5 днів
    if len(sorted_dates) > max_days and sorted_dates[0] == today_str and len(by_date[today_str]) <= 2:
        sorted_dates = sorted_dates[1:1 + max_days]
    else:
        sorted_dates = sorted_dates[:max_days]

    result_days: List[Dict[str, Any]] = []
    for d_str in sorted_dates:
        day_slots = by_date[d_str]
        temps_min = []
        temps_max = []
        pops = []
        chosen_slot = day_slots[len(day_slots) // 2]

        for s in day_slots:
            m = s.get("main") or {}
            t = m.get("temp")
            t_min = m.get("temp_min", t)
            t_max = m.get("temp_max", t)
            if t_min is not None:
                temps_min.append(float(t_min))
            if t_max is not None:
                temps_max.append(float(t_max))
            pop_val = s.get("pop", 0.0)
            if pop_val is not None:
                pops.append(float(pop_val))

            # Віддаємо перевагу денному слоту (12:00 або 15:00) для репрезентативної іконки дня
            dt_t = str(s.get("dt_txt") or "")
            if "12:00:00" in dt_t or "15:00:00" in dt_t:
                chosen_slot = s

        if not temps_min or not temps_max:
            continue

        min_c = round(min(temps_min), 1)
        max_c = round(max(temps_max), 1)
        min_int = int(round(min_c))
        max_int = int(round(max_c))

        w_arr = chosen_slot.get("weather") or [{}]
        w_first = w_arr[0] if w_arr else {}
        raw_icon = str(w_first.get("icon") or "02d")
        # Для денної картки прогнозу використовуємо денну іконку (☀️ замість 🌙)
        day_icon = raw_icon.replace("n", "d") if len(day_icon := raw_icon) == 3 else "02d"
        desc = str(w_first.get("description") or "Хмарно").capitalize()
        pop_pct = int(round(max(pops) * 100)) if pops else 0

        try:
            dt_obj = datetime.strptime(d_str, "%Y-%m-%d")
            wd_short = UA_WEEKDAYS_SHORT[dt_obj.weekday()]
            day_label = f"{wd_short}, {dt_obj.strftime('%d.%m')}"
        except Exception:
            day_label = d_str

        result_days.append({
            "date": d_str,
            "day_label": day_label,
            "temp_min_c": min_c,
            "temp_max_c": max_c,
            "temp_min_formatted": f"{'+' if min_int > 0 else ''}{min_int}°",
            "temp_max_formatted": f"{'+' if max_int > 0 else ''}{max_int}°",
            "icon_code": day_icon,
            "icon_emoji": map_icon_to_emoji(day_icon),
            "description": desc,
            "pop_percent": pop_pct,
        })

    return result_days


async def fetch_openweather_data(
    city: str,
    api_key: str
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Виконує паралельний асинхронний запит до OpenWeatherMap:
    1) Поточна погода (/data/2.5/weather)
    2) Прогноз на 5 днів (/data/2.5/forecast)
    """
    city_clean = city.strip()
    city_lower = city_clean.lower()

    lat_lon = KNOWN_COORDINATES.get(city_lower)

    async with httpx.AsyncClient(timeout=6.0) as client:
        # Якщо координат немає у словнику — запитуємо через Geocoding API
        if not lat_lon:
            try:
                geo_url = f"https://api.openweathermap.org/geo/1.0/direct?q={city_clean},UA&limit=1&appid={api_key}"
                geo_res = await client.get(geo_url)
                if geo_res.status_code == 200:
                    geo_data = geo_res.json()
                    if geo_data and len(geo_data) > 0:
                        lat_lon = (geo_data[0]["lat"], geo_data[0]["lon"])
            except Exception as e:
                logger.warning(f"Помилка геокодування OpenWeather для міста {city_clean}: {e}")

        if lat_lon:
            q_params = f"lat={lat_lon[0]}&lon={lat_lon[1]}&units=metric&lang=ua&appid={api_key}"
        else:
            q_params = f"q={city_clean},UA&units=metric&lang=ua&appid={api_key}"

        weather_url = f"https://api.openweathermap.org/data/2.5/weather?{q_params}"
        forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?{q_params}"

        current_data: Optional[Dict[str, Any]] = None
        forecast_days: List[Dict[str, Any]] = []

        try:
            w_res, f_res = await asyncio.gather(
                client.get(weather_url),
                client.get(forecast_url),
                return_exceptions=True
            )

            if not isinstance(w_res, Exception):
                if w_res.status_code == 200:
                    current_data = w_res.json()
                elif w_res.status_code == 404 and city_lower != "київ":
                    fb_url = f"https://api.openweathermap.org/data/2.5/weather?q=Kyiv,UA&units=metric&lang=ua&appid={api_key}"
                    fb_res = await client.get(fb_url)
                    if fb_res.status_code == 200:
                        current_data = fb_res.json()

            if not isinstance(f_res, Exception):
                if f_res.status_code == 200:
                    forecast_days = parse_5day_forecast(f_res.json())
                elif f_res.status_code == 404 and city_lower != "київ":
                    fb_fc_url = f"https://api.openweathermap.org/data/2.5/forecast?q=Kyiv,UA&units=metric&lang=ua&appid={api_key}"
                    fb_fc_res = await client.get(fb_fc_url)
                    if fb_fc_res.status_code == 200:
                        forecast_days = parse_5day_forecast(fb_fc_res.json())
        except Exception as e:
            logger.error(f"Помилка запиту погоди OpenWeather: {e}")
            return None, []

    return current_data, forecast_days


def _parse_iso_aware(raw_val: Any) -> Optional[datetime]:
    if not raw_val:
        return None
    try:
        s = str(raw_val).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_polygon_coords(poly_str: Any) -> List[Tuple[float, float]]:
    if not poly_str or not isinstance(poly_str, str):
        return []
    pts: List[Tuple[float, float]] = []
    for token in poly_str.strip().split():
        parts = token.split(",")
        if len(parts) == 2:
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return pts


def _point_in_polygon(lat: float, lon: float, polygon: List[Tuple[float, float]]) -> bool:
    if len(polygon) < 3:
        return False
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        yi, xi = polygon[i]
        yj, xj = polygon[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _extract_cap_param(info_obj: Dict[str, Any], name: str) -> str:
    for p in info_obj.get("parameter") or []:
        if isinstance(p, dict) and p.get("valueName") == name:
            return str(p.get("value") or "").strip()
    return ""


def _map_awareness_level(raw_level: str, severity: str) -> Tuple[str, int, str]:
    text = f"{raw_level} {severity}".lower()
    if raw_level.startswith("4") or "red" in text or "extreme" in text:
        return "red", 3, "Червоний (III рівень)"
    if raw_level.startswith("3") or "orange" in text or "severe" in text:
        return "orange", 2, "Помаранчевий (II рівень)"
    if raw_level.startswith("2") or "yellow" in text or "moderate" in text:
        return "yellow", 1, "Жовтий (I рівень)"
    return "none", 0, ""


def _format_kyiv_period(onset_dt: Optional[datetime], expires_dt: Optional[datetime]) -> str:
    try:
        tz = ZoneInfo(get_runtime_timezone())
    except Exception:
        tz = ZoneInfo("Europe/Kyiv")
    parts: List[str] = []
    if onset_dt:
        parts.append(f"з {onset_dt.astimezone(tz).strftime('%d.%m %H:%M')}")
    if expires_dt:
        parts.append(f"до {expires_dt.astimezone(tz).strftime('%d.%m %H:%M')}")
    return " ".join(parts)


def parse_meteoalarm_warnings(
    raw_data: Optional[Dict[str, Any]],
    now_dt: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Парсить JSON-фід MeteoAlarm для України (УкрГМЦ), фільтрує активні небезпечні явища
    та повертає уніфікований список попереджень українською мовою.
    """
    if not raw_data or not isinstance(raw_data, dict):
        return []
    now_ref = now_dt.astimezone(timezone.utc) if now_dt else now_utc(naive=False)
    parsed: List[Dict[str, Any]] = []

    for item in raw_data.get("warnings") or []:
        if not isinstance(item, dict):
            continue
        alert = item.get("alert") or {}
        if str(alert.get("status") or "").lower() != "actual":
            continue
        if str(alert.get("msgType") or "").lower() == "cancel":
            continue

        infos = alert.get("info") or []
        if not isinstance(infos, list) or not infos:
            continue

        uk_info = next((i for i in infos if str(i.get("language") or "").lower().startswith("uk")), None)
        en_info = next((i for i in infos if str(i.get("language") or "").lower().startswith("en")), None)
        primary = uk_info or en_info or infos[0]
        ref_en = en_info or primary

        expires_dt = _parse_iso_aware(primary.get("expires") or ref_en.get("expires"))
        if expires_dt and expires_dt <= now_ref:
            continue

        onset_dt = _parse_iso_aware(
            primary.get("onset") or primary.get("effective") or ref_en.get("onset") or ref_en.get("effective")
        )
        raw_level = _extract_cap_param(primary, "awareness_level") or _extract_cap_param(ref_en, "awareness_level")
        level, level_num, level_ua = _map_awareness_level(raw_level, str(primary.get("severity") or ""))
        if level_num <= 0:
            continue

        raw_type = _extract_cap_param(primary, "awareness_type") or _extract_cap_param(ref_en, "awareness_type")
        type_code = raw_type.split(";")[0].strip() if raw_type else ""
        icon = AWARENESS_TYPE_ICONS.get(type_code, "⚠️")

        areas_uk = [str(a.get("areaDesc") or "").strip() for a in (primary.get("area") or []) if a.get("areaDesc")]
        areas_en = [str(a.get("areaDesc") or "").strip() for a in (ref_en.get("area") or []) if a.get("areaDesc")]

        polygons: List[List[Tuple[float, float]]] = []
        for area_obj in (ref_en.get("area") or []) + (primary.get("area") or []):
            raw_poly = area_obj.get("polygon")
            if isinstance(raw_poly, list):
                for ps in raw_poly:
                    pts = _parse_polygon_coords(ps)
                    if pts:
                        polygons.append(pts)
            elif isinstance(raw_poly, str):
                pts = _parse_polygon_coords(raw_poly)
                if pts:
                    polygons.append(pts)

        event_text = str(primary.get("event") or ref_en.get("event") or "Небезпечне метеорологічне явище").strip()
        desc_text = str(primary.get("description") or ref_en.get("description") or "").strip()
        sender_name = str(primary.get("senderName") or "Український гідрометеорологічний центр").strip()

        parsed.append({
            "id": str(item.get("uuid") or alert.get("identifier") or ""),
            "level": level,
            "level_num": level_num,
            "level_ua": level_ua,
            "icon": icon,
            "event": event_text,
            "description": desc_text,
            "sender": sender_name,
            "areas_uk": areas_uk,
            "areas_en": areas_en,
            "polygons": polygons,
            "onset": onset_dt.isoformat() if onset_dt else None,
            "expires": expires_dt.isoformat() if expires_dt else None,
            "period_formatted": _format_kyiv_period(onset_dt, expires_dt),
            "source": "УкрГМЦ · MeteoAlarm",
        })

    return parsed


def filter_warnings_for_location(
    warnings: List[Dict[str, Any]],
    region_ua: str,
    city_ua: str = "",
    lat_lon: Optional[Tuple[float, float]] = None,
) -> List[Dict[str, Any]]:
    """Відбирає та дедуплікує активні метеопопередження для області або координат об'єкта."""
    if not warnings:
        return []

    stems = [s.lower() for s in OBLAST_EN_MAP.get(region_ua, ())]
    if city_ua:
        c_low = city_ua.strip().lower()
        if c_low and c_low not in stems:
            stems.append(c_low)

    matched: List[Dict[str, Any]] = []
    seen_keys = set()

    for w in warnings:
        area_blob = " ".join((w.get("areas_uk") or []) + (w.get("areas_en") or [])).lower()
        # Exclude pure maritime/port warnings unless coordinates fall inside the polygon
        region_hit = False
        if stems and "порт" not in area_blob and "sea" not in area_blob:
            region_hit = any(st in area_blob for st in stems)

        poly_hit = False
        if not region_hit and lat_lon is not None:
            lat, lon = lat_lon
            for poly in w.get("polygons") or []:
                if _point_in_polygon(lat, lon, poly):
                    poly_hit = True
                    break

        if not (region_hit or poly_hit):
            continue

        dedup_key = (w.get("level_num"), w.get("event"), w.get("description"), w.get("expires"))
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        matched.append({
            "id": w.get("id"),
            "level": w.get("level"),
            "level_num": w.get("level_num"),
            "level_ua": w.get("level_ua"),
            "icon": w.get("icon"),
            "event": w.get("event"),
            "description": w.get("description"),
            "areas": w.get("areas_uk") or w.get("areas_en") or [],
            "onset": w.get("onset"),
            "expires": w.get("expires"),
            "period_formatted": w.get("period_formatted"),
            "source": w.get("source"),
        })

    matched.sort(key=lambda x: (-int(x.get("level_num", 0)), str(x.get("onset") or "")))
    return matched


async def fetch_meteoalarm_ukraine_warnings(force: bool = False) -> List[Dict[str, Any]]:
    """Завантажує та кешує активні попередження УкрГМЦ з MeteoAlarm (15 хв кеш)."""
    global _METEOALARM_CACHE
    now_ts = time.time()
    if not force and _METEOALARM_CACHE and (now_ts - _METEOALARM_CACHE[0]) < METEOALARM_CACHE_TTL_SEC:
        return _METEOALARM_CACHE[1]

    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            res = await client.get(METEOALARM_UA_FEED_URL)
            if res.status_code == 200:
                parsed = parse_meteoalarm_warnings(res.json())
                _METEOALARM_CACHE = (now_ts, parsed)
                return parsed
            logger.warning(f"MeteoAlarm повернув HTTP {res.status_code}")
    except Exception as e:
        logger.warning(f"Не вдалося отримати попередження MeteoAlarm: {e}")

    return _METEOALARM_CACHE[1] if _METEOALARM_CACHE else []


async def get_facility_weather(db: AsyncSession, facility_id: int, force: bool = False) -> Dict[str, Any]:
    """
    Повертає структуровані погодні дані, 5-денний прогноз та офіційні метеопопередження УкрГМЦ для об'єкта.
    """
    facility = await db.get(Facility, facility_id)
    if not facility:
        return {
            "is_available": False,
            "city": "Невідомо",
            "region": "Україна",
            "temp_c": None,
            "description": "Об'єкт не знайдено",
            "forecast": [],
            "warnings": [],
            "has_warnings": False,
            "max_warning_level": "none",
        }

    city_name, region_name = clean_city_and_region(
        city_raw=getattr(facility, "city", None),
        address_raw=facility.address,
        name_raw=facility.name,
    )
    lat_lon = KNOWN_COORDINATES.get(city_name.lower())
    cache_key = f"weather_{city_name.lower()}"
    now_ts = time.time()
    cache_minutes = get_effective_int_setting("weather_cache_minutes", "WEATHER_CACHE_MINUTES", settings.WEATHER_CACHE_MINUTES, min_value=1)
    cache_ttl = cache_minutes * 60

    # Перевірка кешу (якщо не запрошено примусове оновлення і в кеші вже є 5-денний прогноз)
    cached = _WEATHER_CACHE.get(cache_key)
    if not force and cached and (now_ts - cached[0]) < cache_ttl and cached[1].get("forecast"):
        if "warnings" in cached[1]:
            return cached[1]

    api_key = get_effective_str_setting("openweather_api_key", "OPENWEATHER_API_KEY", "")
    all_warnings_task = fetch_meteoalarm_ukraine_warnings(force=force)

    if not api_key:
        all_warnings = await all_warnings_task
        loc_warnings = filter_warnings_for_location(all_warnings, region_name, city_name, lat_lon=lat_lon)
        max_lvl = loc_warnings[0]["level"] if loc_warnings else "none"
        return {
            "is_available": False,
            "city": city_name,
            "region": region_name,
            "temp_c": None,
            "description": "API ключ погоди не налаштовано",
            "icon_emoji": "⛅",
            "generator_tip": "Налаштуйте OpenWeather API Key у розділі «Сервер та Інтеграції» для отримання порад оператору",
            "forecast": [],
            "warnings": loc_warnings,
            "has_warnings": bool(loc_warnings),
            "max_warning_level": max_lvl,
            "updated_at": now_facility().isoformat()
        }

    ow_res, ma_res = await asyncio.gather(
        fetch_openweather_data(city_name, api_key),
        all_warnings_task,
        return_exceptions=True,
    )
    data, forecast_days = (ow_res if not isinstance(ow_res, Exception) else (None, []))
    all_warnings = ma_res if not isinstance(ma_res, Exception) else []

    if data and isinstance(data.get("coord"), dict) and not lat_lon:
        try:
            lat_lon = (float(data["coord"]["lat"]), float(data["coord"]["lon"]))
        except (TypeError, ValueError, KeyError):
            pass

    loc_warnings = filter_warnings_for_location(all_warnings, region_name, city_name, lat_lon=lat_lon)
    max_lvl = loc_warnings[0]["level"] if loc_warnings else "none"

    if not data or "main" not in data:
        # Якщо свіжий запит не вдався, але в пам'яті є попередні дані — повертаємо їх зі свіжими попередженнями
        if cached:
            fallback_res = dict(cached[1])
            fallback_res["warnings"] = loc_warnings
            fallback_res["has_warnings"] = bool(loc_warnings)
            fallback_res["max_warning_level"] = max_lvl
            return fallback_res
        return {
            "is_available": False,
            "city": city_name,
            "region": region_name,
            "temp_c": None,
            "description": "Погодні дані тимчасово недоступні",
            "icon_emoji": "⛅",
            "generator_tip": "Перевірте OpenWeather API Key у розділі «Сервер та Інтеграції» або з'єднання",
            "forecast": [],
            "warnings": loc_warnings,
            "has_warnings": bool(loc_warnings),
            "max_warning_level": max_lvl,
            "updated_at": now_facility().isoformat()
        }

    main = data.get("main", {})
    weather_arr = data.get("weather", [{}])
    weather_first = weather_arr[0] if weather_arr else {}
    icon_code = weather_first.get("icon", "02d")
    desc = weather_first.get("description", "Хмарно з проясненнями").capitalize()
    temp_c = round(float(main.get("temp", 0.0)), 1)
    feels_like_c = round(float(main.get("feels_like", temp_c)), 1)
    humidity = int(main.get("humidity", 0))
    wind = data.get("wind", {})
    wind_mps = round(float(wind.get("speed", 0.0)), 1)
    pressure_hpa = int(main.get("pressure", 1013))
    pressure_mmhg = int(round(pressure_hpa * 0.750062))
    is_rain = "rain" in data or "drizzle" in desc.lower() or "дощ" in desc.lower()

    if not forecast_days and cached and cached[1].get("forecast"):
        forecast_days = cached[1]["forecast"]

    tip = get_generator_weather_tip(temp_c, humidity, is_rain, forecast_days=forecast_days)
    if loc_warnings and int(loc_warnings[0].get("level_num", 0)) >= 2:
        top_w = loc_warnings[0]
        tip += f" Штормове попередження ({top_w['level_ua']}): {top_w['event']}."

    result = {
        "is_available": True,
        "city": city_name,
        "region": region_name,
        "temp_c": temp_c,
        "temp_formatted": f"{'+' if temp_c > 0 else ''}{temp_c:.1f}°C",
        "feels_like_c": feels_like_c,
        "feels_like_formatted": f"{'+' if feels_like_c > 0 else ''}{feels_like_c:.1f}°C",
        "humidity_percent": humidity,
        "wind_speed_mps": wind_mps,
        "pressure_mmhg": pressure_mmhg,
        "description": desc,
        "icon_code": icon_code,
        "icon_emoji": map_icon_to_emoji(icon_code),
        "generator_tip": tip,
        "forecast": forecast_days,
        "warnings": loc_warnings,
        "has_warnings": bool(loc_warnings),
        "max_warning_level": max_lvl,
        "updated_at": now_facility().isoformat()
    }

    _WEATHER_CACHE[cache_key] = (now_ts, result)
    return result


async def check_all_facilities_weather_warnings(db: AsyncSession) -> int:
    """
    Перевіряє активні попередження УкрГМЦ для всіх активних об'єктів та
    надсилає Push-сповіщення (з дедуплікацією за подією і порогом рівня).
    Повертає кількість надісланих сповіщень.
    """
    from datetime import timedelta
    from sqlalchemy import select
    from backend.app.models.notification import NotificationLog
    from backend.app.services.settings_service import get_runtime_setting
    from backend.app.services.notification_service import notify_weather_warning

    if not get_runtime_setting("notifications_enabled", True):
        return 0
    if not get_runtime_setting("notify_weather_warnings", True):
        return 0

    min_lvl_str = str(get_runtime_setting("weather_warning_min_level", "orange") or "orange").strip().lower()
    min_level_num = {"yellow": 1, "orange": 2, "red": 3}.get(min_lvl_str, 2)

    all_warnings = await fetch_meteoalarm_ukraine_warnings(force=False)
    if not all_warnings:
        return 0

    facs = list((await db.execute(select(Facility).order_by(Facility.id.asc()))).scalars().all())
    if not facs:
        return 0

    now_naive = now_utc(naive=True)
    cutoff = now_naive - timedelta(hours=48)
    recent_logs = list(
        (
            await db.execute(
                select(NotificationLog).where(
                    NotificationLog.event_type == "WEATHER_WARNING",
                    NotificationLog.created_at >= cutoff,
                )
            )
        ).scalars().all()
    )

    now_ts = time.time()
    # Prune old in-memory deduplication entries (>48h)
    stale = [k for k, ts in _DISPATCHED_WEATHER_WARNINGS.items() if (now_ts - ts) > 48 * 3600]
    for k in stale:
        _DISPATCHED_WEATHER_WARNINGS.pop(k, None)

    sent_total = 0
    for fac in facs:
        city_name, region_name = clean_city_and_region(
            city_raw=getattr(fac, "city", None),
            address_raw=fac.address,
            name_raw=fac.name,
        )
        lat_lon = KNOWN_COORDINATES.get(city_name.lower())
        loc_warnings = filter_warnings_for_location(all_warnings, region_name, city_name, lat_lon=lat_lon)
        eligible = [w for w in loc_warnings if int(w.get("level_num") or 0) >= min_level_num]
        if not eligible:
            continue

        for w in eligible:
            sig = f"{w.get('level')}|{w.get('event')}|{w.get('expires')}"
            mem_key = (fac.id, sig)
            if mem_key in _DISPATCHED_WEATHER_WARNINGS:
                continue

            # Persistent deduplication across restarts via recent NotificationLog
            already_logged = any(
                lg.facility_id == fac.id
                and str(w.get("event") or "") in (lg.body or "")
                and str(w.get("level_ua") or "") in (lg.title or "")
                and (not w.get("period_formatted") or str(w.get("period_formatted")) in (lg.body or ""))
                for lg in recent_logs
            )
            if already_logged:
                _DISPATCHED_WEATHER_WARNINGS[mem_key] = now_ts
                continue

            res = await notify_weather_warning(
                db=db,
                facility_id=fac.id,
                facility_name=fac.name,
                city_name=city_name,
                level=str(w.get("level") or "yellow"),
                level_ua=str(w.get("level_ua") or "Попередження"),
                icon=str(w.get("icon") or "⚠️"),
                event=str(w.get("event") or "Небезпечне метеорологічне явище"),
                description=str(w.get("description") or ""),
                period_formatted=str(w.get("period_formatted") or ""),
            )
            _DISPATCHED_WEATHER_WARNINGS[mem_key] = now_ts
            if res and not res.get("skipped"):
                sent_total += 1

    return sent_total


async def run_weather_warning_checker_loop(interval_seconds: int = 900) -> None:
    """Фоновий цикл перевірки штормових попереджень УкрГМЦ по всіх об'єктах."""
    from backend.app.database import AsyncSessionLocal
    logger.info("Weather warning checker loop started (interval: %ss)", interval_seconds)
    # Initial short delay after boot so startup completes smoothly
    initial_wait = True
    while True:
        try:
            await asyncio.sleep(60 if initial_wait else interval_seconds)
            initial_wait = False
            async with AsyncSessionLocal() as db:
                await check_all_facilities_weather_warnings(db)
        except asyncio.CancelledError:
            break
        except Exception as ex:
            initial_wait = False
            logger.error("Weather warning checker loop error: %s", ex)
