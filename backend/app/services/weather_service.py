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


def extract_city_from_facility(facility: Facility) -> str:
    """Визначає місто для об'єкта (з поля city або через парсинг адреси/назви)."""
    if getattr(facility, "city", None) and facility.city.strip():
        return facility.city.strip()

    search_text = f"{facility.address or ''} {facility.name or ''}"
    lower = search_text.lower()

    # Перевірка списку відомих міст
    for city_key, _ in KNOWN_COORDINATES.items():
        if city_key in lower:
            # Повертаємо красиву назву з великої літери
            return city_key.title() if "'" not in city_key else "Кам'янське"

    # Спроба регулярного виразу (м. Місто)
    m = re.search(r'(?:м\.|місто|смт)\s*([А-Яа-яІіЇїЄєҐґ\'-]+)', search_text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return "Київ"


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
            "icon_emoji": "⛅"
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
            "icon_emoji": "⛅"
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
