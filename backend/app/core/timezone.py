import datetime
import logging
import re
from typing import Optional, List, Tuple
from zoneinfo import ZoneInfo

from backend.app.config import settings
from backend.app.database import utc_now
from backend.app.services.settings_service import get_runtime_timezone, get_runtime_setting

logger = logging.getLogger(__name__)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def get_facility_tz(tz_name: Optional[str] = None) -> ZoneInfo:
    target_tz = tz_name or get_runtime_timezone() or settings.FACILITY_TIMEZONE or "Europe/Kyiv"
    try:
        return ZoneInfo(target_tz)
    except Exception as e:
        logger.warning(
            "Невідомий або некоректний часовий пояс '%s' (%s), використовується безпечний fallback 'Europe/Kyiv'",
            target_tz, e
        )
        return ZoneInfo("Europe/Kyiv")


def now_utc(naive: bool = True) -> datetime.datetime:
    if naive:
        return utc_now()
    return datetime.datetime.now(datetime.timezone.utc)


def now_facility(tz_name: Optional[str] = None) -> datetime.datetime:
    return datetime.datetime.now(get_facility_tz(tz_name))


def to_facility_time(dt: datetime.datetime, tz_name: Optional[str] = None) -> datetime.datetime:
    if dt.tzinfo is None:
        # If naive, assume it's stored in UTC
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(get_facility_tz(tz_name))


def _parse_time_str(time_str: str) -> Optional[Tuple[int, int]]:
    if not isinstance(time_str, str):
        return None
    m = _TIME_RE.match(time_str.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def is_within_work_schedule(
    schedules: List[dict],
    dt: Optional[datetime.datetime] = None,
    tz_name: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Checks if the given datetime (or now) falls within the allowed generator operating schedule.
    Schedules list format: [{'weekday': -1 or 0-6, 'start_time': '08:00', 'end_time': '20:00', 'is_active': True}]
    Returns (is_allowed, reason_message).
    Fail-closed: if enforce_work_schedule is True and no active schedules exist, launch is forbidden.
    Intervals are half-open: [start_time, end_time).
    Supports daytime and overnight shifts (crossing midnight).
    """
    if not bool(get_runtime_setting("enforce_work_schedule", True)):
        return True, "Контроль робочого графіка вимкнено в налаштуваннях (режим 24/7)"

    if not schedules or not isinstance(schedules, list):
        return False, "Контроль робочого графіка увімкнено, але активний розклад не налаштовано. Запуск заборонено"

    local_dt = to_facility_time(dt, tz_name) if dt else now_facility(tz_name)
    current_weekday = local_dt.weekday()  # 0=Monday, 6=Sunday
    prev_weekday = (current_weekday - 1) % 7
    current_time_str = local_dt.strftime("%H:%M")
    current_time = datetime.time(local_dt.hour, local_dt.minute, local_dt.second, local_dt.microsecond)

    valid_active_schedules = []
    matched_schedule_str = None

    for s in schedules:
        if not isinstance(s, dict):
            logger.warning("Пропущено некоректний запис розкладу (не є dict): %s", s)
            continue

        if not bool(s.get("is_active", True)):
            continue

        raw_wk = s.get("weekday", -1)
        try:
            wk = int(raw_wk)
        except (ValueError, TypeError):
            logger.warning("Пропущено розклад з недійсним днем тижня: %s", raw_wk)
            continue

        if wk not in (-1, 0, 1, 2, 3, 4, 5, 6):
            logger.warning("Пропущено розклад з днем тижня поза діапазоном [-1, 0..6]: %s", wk)
            continue

        st_raw = s.get("start_time", "")
        en_raw = s.get("end_time", "")
        st_hm = _parse_time_str(st_raw)
        en_hm = _parse_time_str(en_raw)

        if not st_hm or not en_hm:
            logger.warning("Пропущено розклад з некоректним форматом часу: '%s' - '%s'", st_raw, en_raw)
            continue

        st_t = datetime.time(st_hm[0], st_hm[1], 0)
        en_t = datetime.time(en_hm[0], en_hm[1], 0)
        range_str = f"{st_raw}-{en_raw}"
        valid_active_schedules.append((wk, st_t, en_t, range_str))

        if matched_schedule_str is not None:
            continue

        if st_t < en_t:
            # Daytime shift: [start_time, end_time)
            if wk in (-1, current_weekday) and (st_t <= current_time < en_t):
                matched_schedule_str = f"{st_raw} - {en_raw}"
        elif st_t > en_t:
            # Overnight shift: started today or started yesterday
            if wk in (-1, current_weekday) and current_time >= st_t:
                matched_schedule_str = f"{st_raw} - {en_raw}"
            elif wk in (-1, prev_weekday) and current_time < en_t:
                matched_schedule_str = f"{st_raw} - {en_raw}"
        else:
            # st_t == en_t (e.g. 00:00 - 00:00 represents 24/7 for this day)
            if st_raw == "00:00" and en_raw == "00:00" and wk in (-1, current_weekday):
                matched_schedule_str = "00:00 - 24:00 (цілодобово)"

    if not valid_active_schedules:
        return False, "Контроль робочого графіка увімкнено, але немає жодного активного розкладу. Запуск заборонено"

    if matched_schedule_str:
        return True, f"Поточний час {current_time_str} в межах дозволеного графіка ({matched_schedule_str})"

    # Format active ranges for current day and general schedules
    applicable_ranges = [
        r_str for (wk, _, _, r_str) in valid_active_schedules
        if wk in (-1, current_weekday)
    ]
    if applicable_ranges:
        ranges_repr = ", ".join(applicable_ranges)
        return False, f"Запуск заборонено: поточний час {current_time_str} поза межами робочого графіка ({ranges_repr})"
    else:
        all_ranges = ", ".join(r_str for (_, _, _, r_str) in valid_active_schedules)
        return False, f"Запуск заборонено: на поточний день ({local_dt.strftime('%A')}) не налаштовано дозволеного робочого часу ({all_ranges})"
