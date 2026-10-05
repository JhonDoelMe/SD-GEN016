import datetime
from zoneinfo import ZoneInfo
import pytest

from backend.app.core.timezone import is_within_work_schedule


def test_schedule_timezone_check():
    schedules = [
        {"weekday": -1, "start_time": "08:00", "end_time": "20:00", "is_active": True}
    ]

    # Test time at 12:00 Kyiv time
    tz = ZoneInfo("Europe/Kyiv")
    allowed_dt = datetime.datetime(2026, 10, 5, 12, 0, 0, tzinfo=tz)
    is_ok, msg = is_within_work_schedule(schedules, allowed_dt)
    assert is_ok is True
    assert "в межах дозволеного графіка" in msg

    # Test time at 03:00 Kyiv time
    forbidden_dt = datetime.datetime(2026, 10, 5, 3, 0, 0, tzinfo=tz)
    is_ok2, msg2 = is_within_work_schedule(schedules, forbidden_dt)
    assert is_ok2 is False
    assert "поза межами робочого графіка" in msg2


@pytest.mark.asyncio
async def test_schedule_enforcement_api(client, superadmin_auth, operator_auth):
    # Configure generator with unreachable schedule window: 03:00 - 03:05
    await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Тестовий генератор",
            "model": "T-100",
            "manufacturer": "Test",
            "serial_number": "SN-001",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 0.0,
            "initial_fuel_tank_level_l": 10.0,
            "work_schedule_start": "03:00",
            "work_schedule_end": "03:01",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )

    # Attempt to start at current daytime
    start_res = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={}
    )
    # Server rejected due to schedule window
    assert start_res.status_code == 400
    assert "Запуск відхилено сервером" in start_res.json()["detail"]
