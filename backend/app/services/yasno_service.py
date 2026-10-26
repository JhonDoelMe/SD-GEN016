import time
import datetime
import asyncio
import logging
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, Tuple, List, Set
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.facility import Facility

logger = logging.getLogger("sd_gen016.yasno")

# Mapping of known Distribution System Operators (ОСР)
DSO_MAP: Dict[int, str] = {
    301: "ДТЕК Дніпровські електромережі (ДнЕМ)",
    303: "ЦЕК (Центральна енергетична компанія)",
    902: "ПрАТ «ДТЕК Київські електромережі»"
}

# In-memory cache: (region_id, dso_id) -> (timestamp, data_dict)
_YASNO_SCHEDULE_CACHE: Dict[Tuple[int, int], Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 900  # 15 minutes cache to protect upstream API

# Set of already dispatched alert keys: (facility_id, date_iso, slot_start_minute)
_SENT_YASNO_ALERTS: Set[Tuple[int, str, int]] = set()


def _format_minutes(mins: int) -> str:
    """Convert minutes from midnight (0..1440) to HH:MM format."""
    if mins >= 1440:
        return "24:00"
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"


def _format_time_left(total_minutes: int) -> str:
    """Format duration into friendly Ukrainian text, e.g. '2 год 15 хв' or '30 хв'."""
    if total_minutes <= 0:
        return "зараз"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} год")
    if minutes > 0 or hours == 0:
        parts.append(f"{minutes} хв")
    return " ".join(parts)


async def fetch_raw_yasno_schedule(
    region_id: int = 3,
    dso_id: int = 301,
    force_refresh: bool = False,
    timeout_sec: float = 8.0
) -> Optional[Dict[str, Any]]:
    """
    Fetch planned outages from YASNO public microservice with in-memory caching.
    """
    cache_key = (region_id, dso_id)
    now_ts = time.time()

    if not force_refresh and cache_key in _YASNO_SCHEDULE_CACHE:
        cached_ts, cached_data = _YASNO_SCHEDULE_CACHE[cache_key]
        if (now_ts - cached_ts) < CACHE_TTL_SECONDS:
            return cached_data

    url = f"https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{region_id}/dsos/{dso_id}/planned-outages"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "uk-UA,uk;q=0.9"
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    _YASNO_SCHEDULE_CACHE[cache_key] = (now_ts, data)
                    return data
            logger.warning(f"YASNO API returned status {resp.status_code} for region {region_id}, dso {dso_id}")
    except Exception as exc:
        logger.warning(f"Error requesting YASNO API ({url}): {exc}")

    # Fallback to stale cache if request failed
    if cache_key in _YASNO_SCHEDULE_CACHE:
        return _YASNO_SCHEDULE_CACHE[cache_key][1]

    return None


def get_facility_outage_schedule(
    facility: Facility,
    raw_schedule: Optional[Dict[str, Any]] = None,
    current_dt: Optional[datetime.datetime] = None
) -> Dict[str, Any]:
    """
    Parse the outage schedule specifically for the given facility and group.
    Generates a full dashboard payload with 24-hour timeline, countdown and statuses.
    """
    facility_tz = ZoneInfo(facility.timezone or "Europe/Kyiv")
    now_local = current_dt or datetime.datetime.now(facility_tz)
    cur_minute = now_local.hour * 60 + now_local.minute

    region_id = facility.yasno_region_id or 3
    dso_id = facility.yasno_dso_id or 301
    dso_name = DSO_MAP.get(dso_id, f"ОСР #{dso_id}")
    group_str = (facility.yasno_group or "").strip()

    base_response = {
        "enabled": bool(facility.yasno_enabled),
        "configured": bool(facility.yasno_enabled and group_str),
        "facility_id": facility.id,
        "facility_name": facility.name,
        "region_id": region_id,
        "dso_id": dso_id,
        "dso_name": dso_name,
        "group": group_str,
        "status": "DISABLED" if not facility.yasno_enabled else "NO_SCHEDULE",
        "status_label": "Вимкнено" if not facility.yasno_enabled else "Графік відсутній",
        "status_color": "muted",
        "message": "Моніторинг графіків вимкнено для цього об'єкта" if not facility.yasno_enabled else "Групу відключень не налаштовано",
        "next_outage": None,
        "timeline_today": [],
        "slots_today": [],
        "slots_tomorrow": [],
        "updated_at": None,
        "is_cached": False,
    }

    if not facility.yasno_enabled or not group_str:
        return base_response

    if raw_schedule is None:
        cache_key = (region_id, dso_id)
        if cache_key in _YASNO_SCHEDULE_CACHE:
            raw_schedule = _YASNO_SCHEDULE_CACHE[cache_key][1]
            base_response["is_cached"] = True

    if not raw_schedule or not isinstance(raw_schedule, dict):
        base_response["message"] = "Дані YASNO тимчасово недоступні (очікується відповідь сервера)"
        return base_response

    # Look up matching group in raw_schedule
    group_data = raw_schedule.get(group_str)
    if not group_data and "." in group_str:
        # Fallback to main group if subgroup not listed
        main_group = group_str.split(".")[0]
        group_data = raw_schedule.get(main_group)
    if not group_data:
        # Try matching any sub-key starting with group (e.g. '3' matches '3.1')
        for k in raw_schedule.keys():
            if k == group_str or k.startswith(f"{group_str}."):
                group_data = raw_schedule[k]
                break

    if not group_data or not isinstance(group_data, dict):
        base_response["message"] = f"Групу «{group_str}» не знайдено в поточному розкладі YASNO"
        return base_response

    today_data = group_data.get("today", {})
    tomorrow_data = group_data.get("tomorrow", {})
    slots_today = today_data.get("slots", [])
    slots_tomorrow = tomorrow_data.get("slots", [])
    updated_on = group_data.get("updatedOn")

    base_response["slots_today"] = slots_today
    base_response["slots_tomorrow"] = slots_tomorrow
    base_response["updated_at"] = updated_on

    # 1. Determine current slot and status right now
    current_slot = None
    for s in slots_today:
        start_m = s.get("start", 0)
        end_m = s.get("end", 1440)
        if start_m <= cur_minute < end_m:
            current_slot = s
            break

    slot_type = current_slot.get("type", "NotPlanned") if current_slot else "NotPlanned"

    if slot_type == "Definite":
        base_response["status"] = "DEFINITE"
        base_response["status_label"] = "Відключення 🔴"
        base_response["status_color"] = "danger"
        remaining = current_slot["end"] - cur_minute
        base_response["message"] = f"Планове відключення до {_format_minutes(current_slot['end'])} (залишилось {_format_time_left(remaining)})"
    elif slot_type == "Probable":
        base_response["status"] = "PROBABLE"
        base_response["status_label"] = "Можливе відключення 🟡"
        base_response["status_color"] = "warning"
        remaining = current_slot["end"] - cur_minute
        base_response["message"] = f"Сіра зона: можливе знеструмлення до {_format_minutes(current_slot['end'])} (залишилось {_format_time_left(remaining)})"
    else:
        base_response["status"] = "NOT_PLANNED"
        base_response["status_label"] = "Світло є 🟢"
        base_response["status_color"] = "success"
        base_response["message"] = "Електропостачання в нормі (відключення не заплановано)"

    # 2. Find next upcoming outage today or tomorrow
    next_outage = None
    # Check remaining slots today
    for s in slots_today:
        st_type = s.get("type", "NotPlanned")
        st_start = s.get("start", 0)
        if st_type in ("Definite", "Probable") and st_start > cur_minute:
            mins_until = st_start - cur_minute
            next_outage = {
                "day": "today",
                "start": _format_minutes(st_start),
                "end": _format_minutes(s.get("end", 1440)),
                "type": st_type,
                "type_label": "Гарантоване" if st_type == "Definite" else "Можливе",
                "minutes_until": mins_until,
                "human_until": _format_time_left(mins_until)
            }
            break

    # If no upcoming outages today, look into tomorrow
    if not next_outage and slots_tomorrow:
        for s in slots_tomorrow:
            st_type = s.get("type", "NotPlanned")
            if st_type in ("Definite", "Probable"):
                st_start = s.get("start", 0)
                mins_until = (1440 - cur_minute) + st_start
                next_outage = {
                    "day": "tomorrow",
                    "start": _format_minutes(st_start),
                    "end": _format_minutes(s.get("end", 1440)),
                    "type": st_type,
                    "type_label": "Гарантоване" if st_type == "Definite" else "Можливе",
                    "minutes_until": mins_until,
                    "human_until": _format_time_left(mins_until)
                }
                break

    base_response["next_outage"] = next_outage
    if base_response["status"] == "NOT_PLANNED" and next_outage:
        day_word = "сьогодні" if next_outage["day"] == "today" else "завтра"
        base_response["message"] = f"Світло є. Наступне знеструмлення {day_word} о {next_outage['start']} (через {next_outage['human_until']})"

    # 3. Construct 24-hour visual timeline for today
    timeline = []
    for h in range(24):
        h_start = h * 60
        h_end = (h + 1) * 60

        # Overlapping slots for this hour
        overlapping_types = [
            s.get("type", "NotPlanned")
            for s in slots_today
            if max(s.get("start", 0), h_start) < min(s.get("end", 1440), h_end)
        ]

        if "Definite" in overlapping_types:
            h_status = "DEFINITE"
        elif "Probable" in overlapping_types:
            h_status = "PROBABLE"
        else:
            h_status = "NOT_PLANNED"

        timeline.append({
            "hour": h,
            "label": f"{h:02d}",
            "time_range": f"{h:02d}:00 – {h+1:02d}:00",
            "status": h_status,
            "is_current": (now_local.hour == h)
        })

    base_response["timeline_today"] = timeline
    return base_response


async def check_and_notify_yasno_outages(db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Scans all facilities with YASNO monitoring enabled.
    Sends push notification to facility operators 25-35 minutes prior to scheduled outages.
    Anti-duplicate protection ensures only 1 notification per facility per outage slot.
    """
    from backend.app.services.notification_service import send_push_notification

    result = await db.execute(
        select(Facility).where(
            Facility.yasno_enabled == True,  # noqa: E712
            Facility.yasno_group.isnot(None),
            Facility.yasno_group != ""
        )
    )
    facilities = result.scalars().all()
    if not facilities:
        return []

    dispatched = []
    today_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    for fac in facilities:
        try:
            region_id = fac.yasno_region_id or 3
            dso_id = fac.yasno_dso_id or 301
            raw = await fetch_raw_yasno_schedule(region_id, dso_id)
            if not raw:
                continue

            parsed = get_facility_outage_schedule(fac, raw)
            next_outage = parsed.get("next_outage")
            if not next_outage or next_outage.get("day") != "today":
                continue

            mins_until = next_outage.get("minutes_until", 999)
            # Notification window: 20 to 35 minutes before start
            if 20 <= mins_until <= 35:
                # Slot start minute for deduplication
                start_str = next_outage.get("start", "00:00")
                try:
                    sh, sm = map(int, start_str.split(":"))
                    start_minute = sh * 60 + sm
                except Exception:
                    start_minute = 0

                alert_key = (fac.id, today_iso, start_minute)
                if alert_key in _SENT_YASNO_ALERTS:
                    continue

                type_label = "планове знеструмлення" if next_outage.get("type") == "Definite" else "можливе відключення"
                title = f"⚡ YASNO: {type_label.capitalize()} (Черга {fac.yasno_group})"
                body = (
                    f"Через {next_outage.get('human_until', '30 хв')} (о {start_str}) на об'єкті «{fac.name}» "
                    f"очікується {type_label}. Перевірте готовність генератора та рівень палива!"
                )

                push_res = await send_push_notification(
                    db=db,
                    title=title,
                    body=body,
                    event_type="YASNO_OUTAGE_ALERT",
                    facility_id=fac.id,
                    url="/"
                )
                _SENT_YASNO_ALERTS.add(alert_key)
                dispatched.append({"facility_id": fac.id, "slot": start_str, "push": push_res})
                logger.info(f"Dispatched YASNO outage alert for facility {fac.id} (group {fac.yasno_group}) at {start_str}")
        except Exception as ex:
            logger.error(f"Error checking YASNO outage for facility {fac.id}: {ex}")

    return dispatched


async def run_yasno_checker_loop(interval_seconds: int = 180):
    """
    Background worker loop that checks upcoming YASNO outages periodically.
    """
    from backend.app.database import AsyncSessionLocal

    logger.info("Starting YASNO blackout outage checker loop...")
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await check_and_notify_yasno_outages(session)
        except asyncio.CancelledError:
            logger.info("YASNO checker loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Unhandled error in YASNO checker loop: {e}", exc_info=True)

        await asyncio.sleep(interval_seconds)
