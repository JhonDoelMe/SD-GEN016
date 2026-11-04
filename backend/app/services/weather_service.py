# -*- coding: utf-8 -*-
import time
import re
import logging
from typing import Dict, Any, Optional, Tuple
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.models.facility import Facility
from backend.app.core.timezone import now_utc

logger = logging.getLogger("sd_gen016.weather")

# In-memory cache: city_key -> (timestamp, weather_dict)
_WEATHER_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

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
    """Очищує оперативний кеш погоди."""
    global _WEATHER_CACHE
    if city:
        _WEATHER_CACHE.pop(f"weather_{city.lower()}", None)
    else:
        _WEATHER_CACHE.clear()


def extract_city_from_facility(facility: Facility) -> str:
    """Визначає чисту назву міста для об'єкта без дублювання області."""
    clean_c, _ = clean_city_and_region(
        city_raw=getattr(facility, "city", None),
        address_raw=facility.address,
        name_raw=facility.name
    )
    return clean_c


def get_generator_weather_tip(temp_c: float, humidity: int, rain: bool) -> str:
    """Формує корисну інженерну пораду для оператора генератора."""
    if temp_c < -10.0:
        return "Сильний мороз! Загусання ДТ, перевірте заряд АКБ та підігрів картера перед пуском."
    elif temp_c < 0.0:
        return "Заморозки: використовуйте зимове ДТ. Рекомендується короткий прогрів двигуна (3–5 хв)."
    elif temp_c > 30.0:
        return "Спека: підвищений ризик перегріву. Контролюйте рівень оливи та вільний приплив повітря."
    elif rain:
        return "Опади: забезпечте надійне укриття панелі керування та електробезпеку контактів."
    else:
        return "Оптимальні погодні умови для стабільної експлуатації генератора."


async def fetch_openweather_data(city: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Виконує прямий асинхронний запит до OpenWeatherMap з автоматичним геолокуванням."""
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

        # Формуємо URL запиту погоди
        if lat_lon:
            weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat_lon[0]}&lon={lat_lon[1]}&units=metric&lang=ua&appid={api_key}"
        else:
            weather_url = f"https://api.openweathermap.org/data/2.5/weather?q={city_clean},UA&units=metric&lang=ua&appid={api_key}"

        try:
            res = await client.get(weather_url)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 404 and city_lower != "київ":
                # Fallback до Києва якщо місто взагалі не знайдено
                fallback_url = f"https://api.openweathermap.org/data/2.5/weather?q=Kyiv,UA&units=metric&lang=ua&appid={api_key}"
                fb_res = await client.get(fallback_url)
                if fb_res.status_code == 200:
                    return fb_res.json()
        except Exception as e:
            logger.error(f"Помилка запиту погоди OpenWeather: {e}")
            return None

    return None


async def get_facility_weather(db: AsyncSession, facility_id: int) -> Dict[str, Any]:
    """
    Повертає структуровані погодні дані для об'єкта з кешуванням в оперативній пам'яті.
    """
    facility = await db.get(Facility, facility_id)
    if not facility:
        return {
            "is_available": False,
            "city": "Невідомо",
            "temp_c": None,
            "description": "Об'єкт не знайдено"
        }

    city_name = extract_city_from_facility(facility)
    cache_key = f"weather_{city_name.lower()}"
    now_ts = time.time()
    cache_ttl = settings.WEATHER_CACHE_MINUTES * 60

    # Перевірка кешу
    cached = _WEATHER_CACHE.get(cache_key)
    if cached and (now_ts - cached[0]) < cache_ttl:
        return cached[1]

    api_key = settings.OPENWEATHER_API_KEY.strip()
    if not api_key:
        return {
            "is_available": False,
            "city": city_name,
            "temp_c": None,
            "description": "API ключ погоди не налаштовано",
            "icon_emoji": "⛅",
            "generator_tip": "Налаштуйте OPENWEATHER_API_KEY у .env для отримання порад оператору",
            "updated_at": now_utc().isoformat()
        }

    data = await fetch_openweather_data(city_name, api_key)
    if not data or "main" not in data:
        # Якщо свіжий запит не вдався, але в пам'яті є попередні дані — повертаємо їх
        if cached:
            return cached[1]
        return {
            "is_available": False,
            "city": city_name,
            "temp_c": None,
            "description": "Погодні дані тимчасово недоступні",
            "icon_emoji": "⛅",
            "generator_tip": "Налаштуйте OPENWEATHER_API_KEY у .env для отримання порад оператору",
            "updated_at": now_utc().isoformat()
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

    result = {
        "is_available": True,
        "city": city_name,
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
        "generator_tip": get_generator_weather_tip(temp_c, humidity, is_rain),
        "updated_at": now_utc().isoformat()
    }

    _WEATHER_CACHE[cache_key] = (now_ts, result)
    return result
