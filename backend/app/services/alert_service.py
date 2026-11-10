# -*- coding: utf-8 -*-
import asyncio
import re
import time
import logging
from datetime import datetime, timezone
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


ALERT_LEVEL_RANK: Dict[str, int] = {
    AlertLevel.GREEN.value: 0,
    AlertLevel.YELLOW.value: 1,
    AlertLevel.RED.value: 2,
}

THREAT_SPECIFICITY_RANK: Dict[str, int] = {
    AlertThreatType.NONE.value: 0,
    AlertThreatType.UNKNOWN.value: 1,
    AlertThreatType.AIR_DEFENSE.value: 2,
    AlertThreatType.DRONES.value: 3,
    AlertThreatType.CRUISE.value: 4,
    AlertThreatType.BOMBS.value: 5,
    AlertThreatType.MIG31K.value: 6,
    AlertThreatType.BALLISTIC.value: 7,
    AlertThreatType.ARTILLERY.value: 8,
}

# In-memory cache: facility_cache_key -> (timestamp, alert_dict)
_ALERTS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

# Global in-memory cache for alerts.in.ua API payload to preserve rate limits
_GLOBAL_ALERTS_IN_UA_CACHE: Dict[str, Any] = {
    "fetched_at": 0.0,
    "last_modified": None,
    "alerts": []
}

# Global in-memory cache for api.ukrainealarm.com v3 payload (strictly 1 req / 60s rate limit)
_GLOBAL_UKRAINE_ALARM_CACHE: Dict[str, Any] = {
    "fetched_at": 0.0,
    "blocked_until": 0.0,
    "data": []
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
    async def fetch_alert(
        self,
        region_name: str,
        city_name: Optional[str] = None,
        force: bool = False
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class AlertsInUaProvider(BaseAlertProvider):
    def __init__(self, token: str):
        self.token = token.strip()

    async def fetch_alert(
        self,
        region_name: str,
        city_name: Optional[str] = None,
        force: bool = False
    ) -> Optional[Dict[str, Any]]:
        if not self.token:
            return None
        global _GLOBAL_ALERTS_IN_UA_CACHE

        now_ts = time.time()
        cache_ttl = settings.ALERTS_CACHE_SECONDS
        cached_alerts = _GLOBAL_ALERTS_IN_UA_CACHE.get("alerts", [])
        fetched_at = _GLOBAL_ALERTS_IN_UA_CACHE.get("fetched_at", 0.0)

        # Повторне використання кешованого запиту всієї карти тривог для збереження лімітів
        # (при force=True дозволяємо запит з If-Modified-Since, але не частіше ніж раз на 3 сек)
        should_fetch = (
            fetched_at == 0.0
            or (now_ts - fetched_at) >= cache_ttl
            or (force and (now_ts - fetched_at) >= 3.0)
        )
        if should_fetch:
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
                        if fetched_at == 0.0:
                            return None
            except Exception as e:
                logger.error(f"Помилка alerts.in.ua запиту: {e}")
                if fetched_at == 0.0:
                    return None
                cached_alerts = _GLOBAL_ALERTS_IN_UA_CACHE["alerts"]

        target_alert = match_target_alert(cached_alerts, region_name, city_name)
        return parse_alert_payload(target_alert, provider_name="alerts.in.ua")


def match_ukraine_alarm_regions(
    data: List[Dict[str, Any]],
    region_name: str,
    city_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Ієрархічний пошук релевантних регіонів у відповіді api.ukrainealarm.com (/api/v3/alerts).
    Підтримує:
    1. Локальні регіони (Community / District) за назвою міста, району або історичним аліасом (Самар/Новомосковськ тощо).
    2. Обласні регіони (State) за назвою області (або м. Київ / м. Харків / м. Запоріжжя).
    """
    if not data or not isinstance(data, list):
        return []

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

    is_kyiv_city = (c_clean == "київ" or ("київ" in r_clean and "область" not in r_clean))
    obl_stem = r_clean.replace("область", "").strip()

    local_matches: List[Dict[str, Any]] = []
    state_matches: List[Dict[str, Any]] = []

    for reg in data:
        if not isinstance(reg, dict) or not reg.get("activeAlerts"):
            continue
        reg_name = (reg.get("regionName") or "").lower().strip()
        reg_type = (reg.get("regionType") or "").lower().strip()

        if is_kyiv_city:
            if reg_name in ("м. київ", "київ") or "м. київ" in reg_name:
                local_matches.append(reg)
            continue

        # Якщо це Київська область, виключаємо м. Київ
        if reg_name in ("м. київ", "київ"):
            continue

        # 1. Перевірка State (області або міст зі спеціальним статусом у UkraineAlarm)
        if reg_type == "state":
            if c_clean and (f"м. {c_clean}" == reg_name or c_clean == reg_name):
                local_matches.append(reg)
                continue
            if obl_stem and (obl_stem in reg_name or reg_name in r_clean):
                state_matches.append(reg)
            continue

        # 2. Перевірка District / Community (райони та громади)
        matched_kw = False
        for kw in city_keywords:
            if kw and kw in reg_name:
                matched_kw = True
                break
        if matched_kw:
            local_matches.append(reg)
            continue

        # Якщо місто не задане, але назва області входить у назву району/громади
        if not c_clean and obl_stem and obl_stem in reg_name:
            state_matches.append(reg)

    return local_matches if local_matches else state_matches


def parse_ukraine_alarm_payload(
    matched_regions: List[Dict[str, Any]],
    provider_name: str = "ukrainealarm.com"
) -> Dict[str, Any]:
    """
    Розбирає список знайдених регіонів api.ukrainealarm.com (/api/v3/alerts)
    з урахуванням v3 структури activeAlerts -> activeAlertLevels (alertLevel: Red/Yellow, reason, createdAt)
    та типів загроз (AIR, ARTILLERY, URBAN_FIGHTS, CHEMICAL, NUCLEAR).
    """
    if not matched_regions:
        return {
            "is_active": False,
            "level": AlertLevel.GREEN.value,
            "threat_type": AlertThreatType.NONE.value,
            "provider": provider_name
        }

    has_red = False
    has_yellow = False
    best_threat = AlertThreatType.UNKNOWN.value
    earliest_started: Optional[str] = None
    best_loc_title: Optional[str] = None

    def update_threat(candidate: str):
        nonlocal best_threat
        if THREAT_SPECIFICITY_RANK.get(candidate, 0) > THREAT_SPECIFICITY_RANK.get(best_threat, 0):
            best_threat = candidate

    for reg in matched_regions:
        reg_title = reg.get("regionName")
        if reg_title and not best_loc_title:
            best_loc_title = reg_title

        active_alerts = reg.get("activeAlerts") or []
        for a in active_alerts:
            al_type = str(a.get("type") or "").upper()
            last_upd = a.get("lastUpdate") or reg.get("lastUpdate")

            # Визначаємо тип загрози з поля type (UkraineAlarm v3)
            if al_type == "ARTILLERY":
                has_red = True
                update_threat(AlertThreatType.ARTILLERY.value)
            elif al_type in ("URBAN_FIGHTS", "CHEMICAL", "NUCLEAR"):
                has_red = True

            # Розбір вкладеного масиву activeAlertLevels (схема v3)
            level_items = a.get("activeAlertLevels") or []
            if level_items:
                for lvl_obj in level_items:
                    al_lvl = str(lvl_obj.get("alertLevel") or "").lower()
                    reason = str(lvl_obj.get("reason") or "").lower()
                    created_at = lvl_obj.get("createdAt") or last_upd
                    if created_at and (not earliest_started or str(created_at) < str(earliest_started)):
                        earliest_started = str(created_at)

                    # Збагачення типу загрози з поля reason (якщо провайдер вказав деталі)
                    if "ballistic" in reason or "баліст" in reason:
                        has_red = True
                        update_threat(AlertThreatType.BALLISTIC.value)
                    elif "mig" in reason or "міг" in reason or "кинджал" in reason:
                        has_red = True
                        update_threat(AlertThreatType.MIG31K.value)
                    elif "kab" in reason or "каб" in reason or "бомб" in reason:
                        has_red = True
                        update_threat(AlertThreatType.BOMBS.value)
                    elif "missile" in reason or "ракет" in reason or "cruise" in reason:
                        has_red = True
                        update_threat(AlertThreatType.CRUISE.value)
                    elif "drone" in reason or "uav" in reason or "бпла" in reason or "шахед" in reason:
                        update_threat(AlertThreatType.DRONES.value)

                    if al_lvl == "yellow":
                        has_yellow = True
                        if best_threat == AlertThreatType.UNKNOWN.value:
                            update_threat(AlertThreatType.DRONES.value)
                    else:
                        has_red = True
            else:
                # Зворотна сумісність із полем level або стандартною тривогою без підрівнів
                legacy_lvl = str(a.get("level") or "").lower()
                if last_upd and (not earliest_started or str(last_upd) < str(earliest_started)):
                    earliest_started = str(last_upd)
                if legacy_lvl == "yellow" or "drone" in al_type.lower():
                    has_yellow = True
                    update_threat(AlertThreatType.DRONES.value)
                else:
                    has_red = True

    final_level = AlertLevel.RED.value if has_red else (AlertLevel.YELLOW.value if has_yellow else AlertLevel.RED.value)
    if final_level == AlertLevel.YELLOW.value and best_threat == AlertThreatType.UNKNOWN.value:
        best_threat = AlertThreatType.DRONES.value

    return {
        "is_active": True,
        "level": final_level,
        "threat_type": best_threat,
        "started_at": earliest_started,
        "location_title": best_loc_title,
        "provider": provider_name
    }


class UkraineAlarmProvider(BaseAlertProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    async def fetch_alert(
        self,
        region_name: str,
        city_name: Optional[str] = None,
        force: bool = False
    ) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None
        global _GLOBAL_UKRAINE_ALARM_CACHE

        now_ts = time.time()
        # Ліміт api.ukrainealarm.com — суворо 1 запит на 60 секунд
        cache_ttl = max(15, getattr(settings, "UKRAINE_ALARM_CACHE_SECONDS", 60))
        fetched_at = _GLOBAL_UKRAINE_ALARM_CACHE.get("fetched_at", 0.0)
        blocked_until = _GLOBAL_UKRAINE_ALARM_CACHE.get("blocked_until", 0.0)
        cached_data = _GLOBAL_UKRAINE_ALARM_CACHE.get("data", [])

        should_fetch = (
            (fetched_at == 0.0 or (now_ts - fetched_at) >= cache_ttl)
            and now_ts >= blocked_until
        )

        if should_fetch:
            url = "https://api.ukrainealarm.com/api/v3/alerts"
            headers = {
                "Authorization": self.api_key,
                "Accept": "application/json"
            }
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        if isinstance(data, list):
                            _GLOBAL_UKRAINE_ALARM_CACHE["data"] = data
                            _GLOBAL_UKRAINE_ALARM_CACHE["fetched_at"] = now_ts
                            _GLOBAL_UKRAINE_ALARM_CACHE["blocked_until"] = 0.0
                            cached_data = data
                            fetched_at = now_ts
                    elif res.status_code == 429:
                        retry_hdr = res.headers.get("retry-after", "60")
                        try:
                            retry_sec = max(10, int(float(retry_hdr)))
                        except ValueError:
                            retry_sec = 60
                        _GLOBAL_UKRAINE_ALARM_CACHE["blocked_until"] = now_ts + retry_sec
                        logger.info(
                            f"ukrainealarm API rate limit (429), cooldown {retry_sec}s — використовуємо кеш"
                        )
                        if fetched_at == 0.0:
                            return None
                    else:
                        logger.warning(f"ukrainealarm API status: {res.status_code}")
                        if fetched_at == 0.0:
                            return None
            except Exception as e:
                logger.error(f"Помилка ukrainealarm запиту: {e}")
                if fetched_at == 0.0:
                    return None

        matched_regs = match_ukraine_alarm_regions(cached_data, region_name, city_name)
        return parse_ukraine_alarm_payload(matched_regs, provider_name="ukrainealarm.com")


class MockAlertProvider(BaseAlertProvider):
    """Емулятор тривог для тестування UI та режимів роботи без бойових ключів."""
    async def fetch_alert(
        self,
        region_name: str,
        city_name: Optional[str] = None,
        force: bool = False
    ) -> Optional[Dict[str, Any]]:
        global _DEMO_ALERT_STATE
        res = dict(_DEMO_ALERT_STATE)
        res["provider"] = "mock"
        return res


def fuse_provider_results(
    res_in_ua: Optional[Dict[str, Any]],
    res_ua_alarm: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Автоматична взаємна звірка двох незалежних провайдерів (alerts.in.ua та ukrainealarm.com).
    Правило безпеки (Страхування від передчасного відбою):
    - При розбіжності статусів або рівнів загрози завжди обирається НАЙВИЩИЙ рівень небезпеки (RED > YELLOW > GREEN).
    - Тип загрози (балістика, ракети, КАБ, МіГ-31К, БПЛА, артобстріл) береться з найбільш деталізованого джерела.
    """
    valid_results = [r for r in (res_in_ua, res_ua_alarm) if isinstance(r, dict)]
    if not valid_results:
        return None

    # Якщо доступний лише один провайдер
    if len(valid_results) == 1:
        single = dict(valid_results[0])
        prov_name = single.get("provider", "alerts.in.ua")
        short_prov = "UkraineAlarm" if "ukrainealarm" in prov_name else "Alerts.in.ua"
        if prov_name == "mock":
            single["verification_status"] = "mock"
            single["verification_note"] = "Демо-режим (тестовий емулятор)"
        else:
            single["verification_status"] = "single_source"
            single["verification_note"] = f"Моніторинг за одним джерелом ({short_prov})"
        return single

    # Обидва провайдери повернули дані — виконуємо автоматичну звірку
    r1, r2 = res_in_ua, res_ua_alarm
    act1 = bool(r1.get("is_active", False))
    act2 = bool(r2.get("is_active", False))
    lvl1 = r1.get("level", AlertLevel.GREEN.value)
    lvl2 = r2.get("level", AlertLevel.GREEN.value)
    rank1 = ALERT_LEVEL_RANK.get(lvl1, 0)
    rank2 = ALERT_LEVEL_RANK.get(lvl2, 0)

    max_rank = max(rank1, rank2)
    final_level = (
        AlertLevel.RED.value if max_rank == 2
        else (AlertLevel.YELLOW.value if max_rank == 1 else AlertLevel.GREEN.value)
    )
    final_active = act1 or act2

    # Визначаємо найбільш специфічний тип загрози
    t1 = r1.get("threat_type", AlertThreatType.NONE.value)
    t2 = r2.get("threat_type", AlertThreatType.NONE.value)

    if not final_active:
        final_threat = AlertThreatType.NONE.value
    else:
        candidates = []
        if act1:
            candidates.append((lvl1, t1))
        if act2:
            candidates.append((lvl2, t2))
        # Спочатку шукаємо специфічну загрозу серед провайдерів з фінальним рівнем,
        # але якщо там unknown (напр. загальна сирена AIR у UkraineAlarm), а інший дає точний тип — враховуємо
        same_lvl_threats = [t for lvl, t in candidates if lvl == final_level and t != AlertThreatType.UNKNOWN.value]
        if same_lvl_threats:
            final_threat = max(same_lvl_threats, key=lambda x: THREAT_SPECIFICITY_RANK.get(x, 0))
        else:
            all_active_threats = [t for _, t in candidates]
            # Якщо фінальний рівень RED (сирена в UkraineAlarm), а другий каже DRONES (yellow),
            # не понижуємо візуальний опис RED-тривоги до БПЛА, якщо немає підтвердження ракет/артилерії
            best_any = max(all_active_threats, key=lambda x: THREAT_SPECIFICITY_RANK.get(x, 0))
            if final_level == AlertLevel.RED.value and best_any == AlertThreatType.DRONES.value and rank1 != rank2:
                final_threat = AlertThreatType.UNKNOWN.value
            else:
                final_threat = best_any

    # Найраніший час початку активної тривоги
    starts = [str(r.get("started_at")) for r in (r1, r2) if r.get("is_active") and r.get("started_at")]
    earliest_start = min(starts) if starts else None

    # Локація (віддаємо перевагу більш точній назві району/громади)
    loc_title = (
        (r1.get("location_title") if act1 else None)
        or (r2.get("location_title") if act2 else None)
        or r1.get("location_title")
        or r2.get("location_title")
    )

    # Формування лаконічного автоматичного статусу звірки провайдерів
    if act1 == act2 and lvl1 == lvl2:
        verification_status = "verified"
        if not final_active:
            verification_note = "Підтверджено обома джерелами (Alerts.in.ua + UkraineAlarm)"
        else:
            verification_note = "Тривогу підтверджено обома джерелами (Alerts.in.ua + UkraineAlarm)"
    elif act1 != act2:
        verification_status = "insurance_hold"
        active_prov_raw = (r1.get("provider") if act1 else r2.get("provider")) or ""
        short_prov = "UkraineAlarm" if "ukrainealarm" in active_prov_raw else "Alerts.in.ua"
        verification_note = f"Страхування відбою: загроза ще активна у {short_prov}"
    else:
        verification_status = "insurance_hold"
        verification_note = "Страхування безпеки: обрано вищий рівень загрози з двох джерел"

    return {
        "is_active": final_active,
        "level": final_level,
        "threat_type": final_threat,
        "started_at": earliest_start,
        "location_title": loc_title,
        "provider": "Alerts.in.ua + UkraineAlarm",
        "verification_status": verification_status,
        "verification_note": verification_note,
    }


def set_demo_alert(level: str, threat_type: str = "none", started_at: Optional[str] = None):
    """Встановлює стан демо-тривоги для перевірки UI."""
    global _DEMO_ALERT_STATE, _ALERTS_CACHE, _GLOBAL_ALERTS_IN_UA_CACHE, _GLOBAL_UKRAINE_ALARM_CACHE
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
    _GLOBAL_UKRAINE_ALARM_CACHE["fetched_at"] = 0.0


def clear_alerts_cache(region: Optional[str] = None) -> None:
    """Очищує кеш статусів тривог."""
    global _ALERTS_CACHE, _GLOBAL_ALERTS_IN_UA_CACHE, _GLOBAL_UKRAINE_ALARM_CACHE
    _ALERTS_CACHE.clear()
    _GLOBAL_ALERTS_IN_UA_CACHE["fetched_at"] = 0.0
    _GLOBAL_UKRAINE_ALARM_CACHE["fetched_at"] = 0.0


async def get_facility_alert(db: AsyncSession, facility_id: int, force: bool = False) -> Dict[str, Any]:
    """
    Повертає статус повітряної тривоги для конкретного об'єкта
    з паралельним опитуванням та автоматичною звіркою двох провайдерів
    (alerts.in.ua + api.ukrainealarm.com) за правилом найгіршого сценарію (страхування від передчасного відбою).
    """
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

    # Перевірка кешу об'єкта (якщо не запрошено примусове оновлення)
    cached = _ALERTS_CACHE.get(cache_key)
    if not force and cached and (now_ts - cached[0]) < cache_ttl:
        return cached[1]

    # Ініціалізація провайдерів
    token_in_ua = settings.ALERTS_IN_UA_TOKEN.strip()
    key_alarm = settings.UKRAINE_ALARM_API_KEY.strip()

    res_in_ua: Optional[Dict[str, Any]] = None
    res_ua_alarm: Optional[Dict[str, Any]] = None

    tasks = []
    task_names = []
    if token_in_ua:
        tasks.append(AlertsInUaProvider(token_in_ua).fetch_alert(region_name, city_name, force=force))
        task_names.append("in_ua")
    if key_alarm:
        tasks.append(UkraineAlarmProvider(key_alarm).fetch_alert(region_name, city_name, force=force))
        task_names.append("ua_alarm")

    if tasks:
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for name, outcome in zip(task_names, outcomes):
            if isinstance(outcome, Exception):
                logger.warning(f"Збій провайдера тривог ({name}): {outcome}")
            elif isinstance(outcome, dict):
                if name == "in_ua":
                    res_in_ua = outcome
                elif name == "ua_alarm":
                    res_ua_alarm = outcome

    raw_result = fuse_provider_results(res_in_ua, res_ua_alarm)

    # Якщо бойових ключів немає або обидва зовнішні запити не дали результату
    if not raw_result:
        if cached and (token_in_ua or key_alarm):
            return cached[1]
        mock_res = await MockAlertProvider().fetch_alert(region_name, city_name, force=force)
        raw_result = fuse_provider_results(mock_res, None)

    level = raw_result.get("level", AlertLevel.GREEN.value)
    threat_type = raw_result.get("threat_type", AlertThreatType.NONE.value)
    title, threat_icon = get_threat_display_info(threat_type, level)

    icon_map = {
        "green": "🟢",
        "yellow": "🟡",
        "red": "🔴"
    }

    started_at_val = raw_result.get("started_at")
    duration_minutes = raw_result.get("duration_minutes", 0)
    if raw_result.get("is_active") and started_at_val and not duration_minutes:
        try:
            dt_start = datetime.fromisoformat(str(started_at_val).replace("Z", "+00:00"))
            if dt_start.tzinfo is None:
                dt_start = dt_start.replace(tzinfo=timezone.utc)
            diff_sec = (now_utc() - dt_start).total_seconds()
            if diff_sec > 0:
                duration_minutes = max(1, int(diff_sec // 60))
        except Exception:
            duration_minutes = 0

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
        "started_at": started_at_val,
        "duration_minutes": duration_minutes,
        "operator_advice": get_operator_safety_advice(level, threat_type),
        "provider": raw_result.get("provider", "local"),
        "verification_status": raw_result.get("verification_status", "single_source"),
        "verification_note": raw_result.get("verification_note", ""),
        "updated_at": now_utc().isoformat()
    }

    _ALERTS_CACHE[cache_key] = (now_ts, result)
    return result
