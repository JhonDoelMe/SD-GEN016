# -*- coding: utf-8 -*-
import time
import logging
from enum import Enum
from typing import Dict, Any, Optional, Tuple, List
import httpx
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.models.facility import Facility
from backend.app.core.timezone import now_utc

logger = logging.getLogger("sd_gen016.alerts")


class AlertLevel(str, Enum):
    GREEN = "green"    # Чисте небо / Відбій
    YELLOW = "yellow"  # Підвищена загроза (БПЛА / Шахеди, тактична авіація)
    RED = "red"        # Критична загроза (Балістика, крилаті ракети, МіГ-31К, КАБ, артобстріл)


class AlertThreatType(str, Enum):
    NONE = "none"
    DRONES = "drones"
    BALLISTIC = "ballistic"
    CRUISE = "cruise"
    MIG31K = "mig31k"
    BOMBS = "bombs"
    ARTILLERY = "artillery"
    AIR_DEFENSE = "air_defense"
    UNKNOWN = "unknown"


# In-memory cache: facility_cache_key -> (timestamp, alert_dict)
_ALERTS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

# Global in-memory cache for alerts.in.ua API payload to preserve rate limits
_GLOBAL_ALERTS_IN_UA_CACHE: Dict[str, Any] = {
    "fetched_at": 0.0,
    "last_modified": None,
    "alerts": []
}

# Mapping of city names/stems to alias keywords (for matching raions, hromadas, and renames)
CITY_SEARCH_ALIASES: Dict[str, List[str]] = {
    "самар": ["самар", "новомосковськ"],
    "новомосковськ": ["самар", "новомосковськ"],
    "дніпро": ["дніпро", "дніпровськ"],
    "кам'янське": ["кам'янськ", "камянськ", "дніпродзержинськ"],
    "кривий ріг": ["кривий ріг", "криворізьк"],
    "нікополь": ["нікополь", "нікопол"],
    "павлоград": ["павлоград", "павлоградськ"],
    "синельникове": ["синельников", "синельниківськ"],
    "київ": ["київ", "м. київ"],
    "біла церква": ["біла церква", "білоцерківськ"],
    "бровари": ["бровари", "броварськ"],
    "бориспіль": ["бориспіль", "бориспільськ"],
    "ірпінь": ["ірпінь", "ірпінськ"],
    "буча": ["буча", "бучанськ"],
    "кременчук": ["кременчук", "кременчуцьк"],
    "умань": ["умань", "уманськ"],
    "ізмаїл": ["ізмаїл", "ізмаїльськ"],
    "дрогобич": ["дрогобич", "дрогобицьк"],
    "стрий": ["стрий", "стрийськ"],
    "червоноград": ["червоноград", "шептицьк"],
    "шептицький": ["шептицьк", "червоноград"],
}

# Circuit breaker state
_PRIMARY_FAILS_COUNT = 0
_PRIMARY_BLOCKED_UNTIL = 0.0

# Demo mock state for manual testing & automated test verification
_DEMO_ALERT_STATE: Dict[str, Any] = {
    "is_active": False,
    "level": "green",
    "threat_type": "none",
    "threat_title": "Чисте небо (Відбій тривоги)",
    "threat_icon": "🛡️",
    "started_at": None,
    "duration_minutes": 0,
}

# Mapping city to Ukrainian Oblast (Region)
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
}


def get_threat_display_info(threat_type: str, level: str) -> Tuple[str, str]:
    """Повертає назву загрози та відповідну іконку для плашки."""
    t = (threat_type or "").lower()
    if t in ("ballistic", "ballistic_missiles"):
        return "Балістична небезпека", "🚀"
    if t in ("cruise", "cruise_missiles", "unspecified_missiles"):
        return "Ракетна небезпека", "🚀"
    if t in ("mig31k", "mig31k_departure"):
        return "Зліт МіГ-31К (Кинджал)", "🚀"
    if t in ("drones", "uav"):
        return "Загроза ударних БПЛА", "🛸"
    if t in ("bombs", "guided_aerial_bombs", "kab"):
        return "Загроза КАБ (авіабомби)", "💣"
    if t in ("artillery", "shelling"):
        return "Загроза артобстрілу", "💥"
    if t in ("air_defense",):
        return "Робота сил ППО", "🛡️"
    if level == "red":
        return "Повітряна тривога (Ракети)", "🚨"
    if level == "yellow":
        return "Підвищена загроза (БПЛА)", "🛸"
    return "Небо чисте (Відбій)", "🟢"


def get_operator_safety_advice(level: str, threat_type: str) -> str:
    """Формує обов'язкову інструкцію безпеки для оператора генератора."""
    t = (threat_type or "").lower()
    if t in ("artillery", "artillery_shelling", "shelling"):
        return (
            "НЕБЕЗПЕКА АРТОБСТРІЛУ! "
            "Операторам категорично заборонено перебувати біля генератора та паливних ємностей. "
            "Негайно прямуйте до капітального укриття!"
        )
    if level == "red":
        return (
            "КРИТИЧНА НЕБЕЗПЕКА! Миттєвий підліт швидкісних цілей. "
            "Операторам суворо заборонено перебувати просто неба біля генератора чи баків пального. "
            "Негайно прямуйте в укриття!"
        )
    elif level == "yellow":
        return (
            "ПІДВИЩЕНА ЗАГРОЗА (БПЛА / Дрони). "
            "Обмежте перебування біля генератора та паливних складів. "
            "Перевірте готовність системи аварійного резерву на випадок пошкодження мереж."
        )
    else:
        return "Тривоги немає. Дозволено всі штатні регламентні роботи, заправку бака та оприбуткування палива."


def match_target_alert(
    alerts: List[Dict[str, Any]],
    region_name: str,
    city_name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Знаходить найбільш релевантну та пріоритетну активну тривогу для локації об'єкта.
    Підтримує ієрархічний пошук:
    1. Локальна тривога (громада / місто / район) з найвищим рівнем небезпеки (RED > YELLOW).
    2. Загальнообласна тривога (oblast).
    """
    if not alerts:
        return None

    import re
    r_clean = (region_name or "").lower().strip()
    c_clean = (city_name or "").lower().strip()

    c_clean = re.sub(r'^(?:м\.|місто|смт|с\.)\s*', '', c_clean).strip()
    r_clean = re.sub(r'^(?:м\.|місто)\s*', '', r_clean).strip()

    city_keywords = set()
    if c_clean:
        city_keywords.add(c_clean)
        if c_clean in CITY_SEARCH_ALIASES:
            city_keywords.update(CITY_SEARCH_ALIASES[c_clean])
        if len(c_clean) >= 5:
            city_keywords.add(c_clean[:5])

    matching_local_alerts: List[Dict[str, Any]] = []
    matching_oblast_alerts: List[Dict[str, Any]] = []

    is_kyiv_city = (c_clean == "київ" or ("київ" in r_clean and "область" not in r_clean))

    for a in alerts:
        loc_title = (a.get("location_title") or "").lower()
        loc_oblast = (a.get("location_oblast") or "").lower()
        loc_raion = (a.get("location_raion") or "").lower()
        loc_type = (a.get("location_type") or "").lower()

        # Спеціальний випадок: м. Київ
        if is_kyiv_city:
            if "м. київ" in loc_title or loc_title == "київ" or (loc_oblast == "м. київ" and loc_type in ("oblast", "city")):
                matching_local_alerts.append(a)
            continue

        # Перевірка належності до однієї області
        same_oblast = False
        if r_clean:
            obl_stem = r_clean.replace("область", "").strip()
            if obl_stem and (obl_stem in loc_oblast or obl_stem in loc_title):
                same_oblast = True

        if not same_oblast:
            continue

        # Якщо це тривога на всю область
        if loc_type == "oblast":
            matching_oblast_alerts.append(a)
            continue

        # Якщо це тривога на рівні району, міста чи громади
        matched_city = False
        for kw in city_keywords:
            if kw and (kw in loc_title or kw in loc_raion):
                matched_city = True
                break

        if matched_city:
            matching_local_alerts.append(a)

    def alert_priority(al: Dict[str, Any]) -> Tuple[int, int, str]:
        lvl = (al.get("alert_level") or "").lower()
        lvl_score = 2 if lvl == "red" else (1 if lvl == "yellow" else 0)
        has_red_threat = 1 if any((th.get("level") == "red") for th in (al.get("threats") or [])) else 0
        started = al.get("started_at") or ""
        return (lvl_score, has_red_threat, started)

    if matching_local_alerts:
        matching_local_alerts.sort(key=alert_priority, reverse=True)
        return matching_local_alerts[0]

    if matching_oblast_alerts:
        matching_oblast_alerts.sort(key=alert_priority, reverse=True)
        return matching_oblast_alerts[0]

    return None


def parse_alert_payload(target_alert: Optional[Dict[str, Any]], provider_name: str = "alerts.in.ua") -> Dict[str, Any]:
    """Розбирає структуру тривоги API alerts.in.ua на єдині системні сутності SD-GEN016."""
    if not target_alert:
        return {
            "is_active": False,
            "level": AlertLevel.GREEN.value,
            "threat_type": AlertThreatType.NONE.value,
            "provider": provider_name
        }

    # Базовий рівень з поля alert_level (підтримує "red" та "yellow" навіть без масиву threats)
    base_level = (target_alert.get("alert_level") or "red").lower()
    alert_type_raw = (target_alert.get("alert_type") or "").lower()

    if alert_type_raw in ("artillery_shelling", "shelling"):
        main_threat_type = AlertThreatType.ARTILLERY.value
        base_level = AlertLevel.RED.value
    elif alert_type_raw in ("urban_fights",):
        main_threat_type = AlertThreatType.UNKNOWN.value
        base_level = AlertLevel.RED.value
    elif alert_type_raw in ("chemical",):
        main_threat_type = AlertThreatType.UNKNOWN.value
        base_level = AlertLevel.RED.value
    elif alert_type_raw in ("nuclear",):
        main_threat_type = AlertThreatType.UNKNOWN.value
        base_level = AlertLevel.RED.value
    elif base_level == "yellow":
        main_threat_type = AlertThreatType.DRONES.value
    else:
        main_threat_type = AlertThreatType.UNKNOWN.value

    has_red = (base_level == "red")
    has_yellow = (base_level == "yellow")

    threats = target_alert.get("threats") or []
    for th in threats:
        th_type = str(th.get("threat_type", "")).lower()
        th_level = str(th.get("level", "")).lower()

        if th_level == "red" or th_type in (
            "ballistic_missiles", "cruise_missiles", "unspecified_missiles",
            "mig31k_departure", "guided_aerial_bombs", "artillery"
        ):
            has_red = True
            if th_type in ("ballistic_missiles", "ballistic"):
                main_threat_type = AlertThreatType.BALLISTIC.value
            elif th_type in ("cruise_missiles", "unspecified_missiles", "cruise"):
                main_threat_type = AlertThreatType.CRUISE.value
            elif th_type in ("mig31k_departure", "mig31k"):
                main_threat_type = AlertThreatType.MIG31K.value
            elif th_type in ("guided_aerial_bombs", "bombs", "kab"):
                main_threat_type = AlertThreatType.BOMBS.value
            elif th_type in ("artillery", "artillery_shelling"):
                main_threat_type = AlertThreatType.ARTILLERY.value
            else:
                main_threat_type = th_type
        elif th_level == "yellow" or th_type in ("drones", "air_defense", "tactic_aircraft_activity"):
            has_yellow = True
            if not has_red:
                if th_type in ("drones", "uav"):
                    main_threat_type = AlertThreatType.DRONES.value
                elif th_type in ("air_defense",):
                    main_threat_type = AlertThreatType.AIR_DEFENSE.value
                else:
                    main_threat_type = th_type

    final_level = AlertLevel.RED.value if has_red else (AlertLevel.YELLOW.value if has_yellow else AlertLevel.RED.value)

    return {
        "is_active": True,
        "level": final_level,
        "threat_type": main_threat_type,
        "started_at": target_alert.get("started_at"),
        "location_title": target_alert.get("location_title"),
        "provider": provider_name
    }


class BaseAlertProvider:
    async def fetch_alert(self, region_name: str, city_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class AlertsInUaProvider(BaseAlertProvider):
    def __init__(self, token: str):
        self.token = token.strip()

    async def fetch_alert(self, region_name: str, city_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.token:
            return None
        global _GLOBAL_ALERTS_IN_UA_CACHE

        now_ts = time.time()
        cache_ttl = settings.ALERTS_CACHE_SECONDS
        cached_alerts = _GLOBAL_ALERTS_IN_UA_CACHE.get("alerts", [])

        # Повторне використання кешованого запиту всієї карти тривог для збереження лімітів
        if (now_ts - _GLOBAL_ALERTS_IN_UA_CACHE.get("fetched_at", 0.0)) >= cache_ttl or not cached_alerts:
            url = "https://api.alerts.in.ua/v1/alerts/active.json"
            headers = {"Authorization": f"Bearer {self.token}"}
            last_mod = _GLOBAL_ALERTS_IN_UA_CACHE.get("last_modified")
            if last_mod and cached_alerts:
                headers["If-Modified-Since"] = last_mod

            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    res = await client.get(url, headers=headers)
                    if res.status_code == 304:
                        # Дані не змінилися (HTTP 304 Not Modified)
                        _GLOBAL_ALERTS_IN_UA_CACHE["fetched_at"] = now_ts
                    elif res.status_code == 200:
                        data = res.json()
                        _GLOBAL_ALERTS_IN_UA_CACHE["alerts"] = data.get("alerts", [])
                        _GLOBAL_ALERTS_IN_UA_CACHE["last_modified"] = res.headers.get("last-modified")
                        _GLOBAL_ALERTS_IN_UA_CACHE["fetched_at"] = now_ts
                        cached_alerts = _GLOBAL_ALERTS_IN_UA_CACHE["alerts"]
                    else:
                        logger.warning(f"alerts.in.ua API status: {res.status_code}")
                        if not cached_alerts:
                            return None
            except Exception as e:
                logger.error(f"Помилка alerts.in.ua запиту: {e}")
                if not cached_alerts:
                    raise
                cached_alerts = _GLOBAL_ALERTS_IN_UA_CACHE["alerts"]

        target_alert = match_target_alert(cached_alerts, region_name, city_name)
        return parse_alert_payload(target_alert, provider_name="alerts.in.ua")


class UkraineAlarmProvider(BaseAlertProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    async def fetch_alert(self, region_name: str, city_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None
        url = "https://api.ukrainealarm.com/api/v3/alerts"
        headers = {"Authorization": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code != 200:
                    logger.warning(f"ukrainealarm API status: {res.status_code}")
                    return None
                data = res.json()
                r_lower = (region_name or "").lower()
                c_lower = (city_name or "").lower()

                target_region = None
                for reg in data:
                    name = (reg.get("regionName") or "").lower()
                    if r_lower in name or name in r_lower or (c_lower and c_lower in name):
                        target_region = reg
                        break

                if not target_region or not target_region.get("activeAlerts"):
                    return {
                        "is_active": False,
                        "level": AlertLevel.GREEN.value,
                        "threat_type": AlertThreatType.NONE.value,
                        "provider": "ukrainealarm.com"
                    }

                active_alerts = target_region.get("activeAlerts", [])
                has_red = False
                has_yellow = False
                main_threat = AlertThreatType.UNKNOWN.value

                for a in active_alerts:
                    al_type = str(a.get("type", "")).lower()
                    al_level = str(a.get("level", "")).lower()
                    if al_level == "red" or al_type in ("artillery", "chemical", "nuclear"):
                        has_red = True
                        main_threat = al_type
                    elif al_level == "yellow" or "drone" in al_type:
                        has_yellow = True
                        if not has_red:
                            main_threat = "drones"

                level = AlertLevel.RED.value if (has_red or not active_alerts) else (AlertLevel.YELLOW.value if has_yellow else AlertLevel.RED.value)
                return {
                    "is_active": True,
                    "level": level,
                    "threat_type": main_threat,
                    "provider": "ukrainealarm.com"
                }
        except Exception as e:
            logger.error(f"Помилка ukrainealarm запиту: {e}")
            raise


class MockAlertProvider(BaseAlertProvider):
    """Емулятор тривог для тестування UI та режимів роботи без бойових ключів."""
    async def fetch_alert(self, region_name: str, city_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        global _DEMO_ALERT_STATE
        res = dict(_DEMO_ALERT_STATE)
        res["provider"] = "mock"
        return res


def set_demo_alert(level: str, threat_type: str = "none", started_at: Optional[str] = None):
    """Встановлює стан демо-тривоги для перевірки UI."""
    global _DEMO_ALERT_STATE, _ALERTS_CACHE, _GLOBAL_ALERTS_IN_UA_CACHE
    is_active = level in ("yellow", "red")
    title, icon = get_threat_display_info(threat_type, level)
    _DEMO_ALERT_STATE = {
        "is_active": is_active,
        "level": level,
        "threat_type": threat_type,
        "threat_title": title,
        "threat_icon": icon,
        "started_at": started_at or (now_utc().isoformat() if is_active else None),
        "duration_minutes": 15 if is_active else 0,
    }
    _ALERTS_CACHE.clear()
    _GLOBAL_ALERTS_IN_UA_CACHE["fetched_at"] = 0.0


def clear_alerts_cache(region: Optional[str] = None) -> None:
    """Очищує кеш статусів тривог."""
    global _ALERTS_CACHE, _GLOBAL_ALERTS_IN_UA_CACHE
    _ALERTS_CACHE.clear()
    _GLOBAL_ALERTS_IN_UA_CACHE["fetched_at"] = 0.0


async def get_facility_alert(db: AsyncSession, facility_id: int) -> Dict[str, Any]:
    """
    Повертає статус повітряної тривоги для конкретного об'єкта
    з кешуванням (15 сек), підтримкою Primary + Fallback провайдерів та Circuit Breaker.
    """
    global _PRIMARY_FAILS_COUNT, _PRIMARY_BLOCKED_UNTIL

    facility = await db.get(Facility, facility_id)
    if not facility:
        return {
            "is_active": False,
            "level": AlertLevel.GREEN.value,
            "threat_title": "Об'єкт не знайдено",
            "region_name": "Україна",
            "icon": "🟢"
        }

    # Уніфіковане визначення чистого міста та області без дублювання
    from backend.app.services.weather_service import clean_city_and_region
    city_name, region_name = clean_city_and_region(
        city_raw=getattr(facility, "city", None),
        address_raw=facility.address,
        name_raw=facility.name
    )
    cache_key = f"alert_fac_{facility_id}_{region_name.lower()}_{city_name.lower()}"
    now_ts = time.time()
    cache_ttl = settings.ALERTS_CACHE_SECONDS

    # Перевірка кешу
    cached = _ALERTS_CACHE.get(cache_key)
    if cached and (now_ts - cached[0]) < cache_ttl:
        return cached[1]

    # Ініціалізація провайдерів
    token_in_ua = settings.ALERTS_IN_UA_TOKEN.strip()
    key_alarm = settings.UKRAINE_ALARM_API_KEY.strip()

    primary_provider: Optional[BaseAlertProvider] = None
    fallback_provider: Optional[BaseAlertProvider] = None

    if token_in_ua:
        primary_provider = AlertsInUaProvider(token_in_ua)
        if key_alarm:
            fallback_provider = UkraineAlarmProvider(key_alarm)
    elif key_alarm:
        primary_provider = UkraineAlarmProvider(key_alarm)

    # Якщо бойових ключів немає — використовуємо повноцінний MockAlertProvider
    if not primary_provider:
        primary_provider = MockAlertProvider()

    raw_result: Optional[Dict[str, Any]] = None

    # Circuit breaker: перевіряємо чи Primary не заблокований через помилки
    use_primary = (now_ts >= _PRIMARY_BLOCKED_UNTIL)

    if use_primary:
        try:
            raw_result = await primary_provider.fetch_alert(region_name, city_name)
            _PRIMARY_FAILS_COUNT = 0
        except Exception as e:
            _PRIMARY_FAILS_COUNT += 1
            logger.warning(f"Збій основного провайдера тривог ({_PRIMARY_FAILS_COUNT}/2): {e}")
            if _PRIMARY_FAILS_COUNT >= 2:
                _PRIMARY_BLOCKED_UNTIL = now_ts + 180  # Блокування на 3 хвилини
                logger.error("Основний провайдер тривог тимчасово заблоковано на 3 хвилини. Перемикання на резерв.")

    # Fallback провайдер у разі потреби
    if not raw_result and fallback_provider:
        try:
            raw_result = await fallback_provider.fetch_alert(region_name, city_name)
        except Exception as e:
            logger.error(f"Збій резервного провайдера тривог: {e}")

    # Якщо всі зовнішні запити впали, але є кеш — повертаємо кеш
    if not raw_result:
        if cached:
            return cached[1]
        raw_result = await MockAlertProvider().fetch_alert(region_name, city_name)

    level = raw_result.get("level", AlertLevel.GREEN.value)
    threat_type = raw_result.get("threat_type", AlertThreatType.NONE.value)
    title, threat_icon = get_threat_display_info(threat_type, level)

    icon_map = {
        "green": "🟢",
        "yellow": "🟡",
        "red": "🔴"
    }

    result = {
        "is_active": raw_result.get("is_active", False),
        "level": level,
        "threat_type": threat_type,
        "threat_title": title,
        "threat_icon": threat_icon,
        "icon": icon_map.get(level, "🟢"),
        "city": city_name,
        "region_name": region_name,
        "location_title": raw_result.get("location_title") or region_name,
        "started_at": raw_result.get("started_at"),
        "operator_advice": get_operator_safety_advice(level, threat_type),
        "provider": raw_result.get("provider", "local"),
        "updated_at": now_utc().isoformat()
    }

    _ALERTS_CACHE[cache_key] = (now_ts, result)
    return result
