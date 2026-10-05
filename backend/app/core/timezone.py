import datetime
from zoneinfo import ZoneInfo
from typing import Optional, List
from backend.app.config import settings


def get_facility_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.FACILITY_TIMEZONE)
    except Exception:
        return ZoneInfo("Europe/Kyiv")


def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def now_facility() -> datetime.datetime:
    return datetime.datetime.now(get_facility_tz())


def to_facility_time(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None:
        # If naive, assume it's stored in UTC
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(get_facility_tz())


def is_within_work_schedule(
    schedules: List[dict],
    dt: Optional[datetime.datetime] = None
) -> tuple[bool, str]:
    """
    Checks if the given datetime (or now) falls within the allowed generator operating schedule.
    Schedules list format: [{'weekday': -1 or 0-6, 'start_time': '08:00', 'end_time': '20:00', 'is_active': True}]
    Returns (is_allowed, reason_message)
    """
    if not schedules:
        # If no schedule is configured, default to allowed or require setup
        return True, "Розклад не обмежений"

    local_dt = to_facility_time(dt) if dt else now_facility()
    current_weekday = local_dt.weekday()  # 0=Monday, 6=Sunday
    current_time_str = local_dt.strftime("%H:%M")

    # Filter active schedules matching either this specific weekday or all days (-1)
    applicable_schedules = [
        s for s in schedules
        if s.get("is_active", True) and (s.get("weekday") in (-1, current_weekday))
    ]

    if not applicable_schedules:
        return False, f"На поточний день ({local_dt.strftime('%A')}) не налаштовано дозволеного робочого часу"

    for s in applicable_schedules:
        start_str = s.get("start_time", "08:00")
        end_str = s.get("end_time", "20:00")
        if start_str <= current_time_str <= end_str:
            return True, f"Поточний час {current_time_str} в межах дозволеного графіка ({start_str} - {end_str})"

    # If none matched
    active_ranges = ", ".join(f"{s.get('start_time')}-{s.get('end_time')}" for s in applicable_schedules)
    return False, f"Запуск заборонено: поточний час {current_time_str} поза межами робочого графіка ({active_ranges})"
