import pytest
import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch

from backend.app.models.facility import Facility
from backend.app.services.yasno_service import (
    get_facility_outage_schedule,
    check_and_notify_yasno_outages,
    _format_minutes,
    _format_time_left,
    _SENT_YASNO_ALERTS,
)


def test_format_helpers():
    assert _format_minutes(0) == "00:00"
    assert _format_minutes(540) == "09:00"
    assert _format_minutes(1290) == "21:30"
    assert _format_minutes(1440) == "24:00"

    assert _format_time_left(30) == "30 хв"
    assert _format_time_left(135) == "2 год 15 хв"
    assert _format_time_left(0) == "зараз"


def test_get_facility_outage_schedule_disabled():
    fac = Facility(id=1, name="Самар Тест", yasno_enabled=False, yasno_group="3.2")
    res = get_facility_outage_schedule(fac)
    assert res["enabled"] is False
    assert res["status"] == "DISABLED"


def test_get_facility_outage_schedule_parsing():
    fac = Facility(id=1, name="Самар Головний", yasno_enabled=True, yasno_group="3.2", yasno_region_id=3, yasno_dso_id=301)
    
    mock_raw = {
        "3.2": {
            "today": {
                "slots": [
                    {"start": 0, "end": 1080, "type": "NotPlanned"},      # 00:00 - 18:00
                    {"start": 1080, "end": 1260, "type": "Probable"},     # 18:00 - 21:00 (yellow)
                    {"start": 1260, "end": 1440, "type": "Definite"},     # 21:00 - 24:00 (red)
                ],
                "date": "2026-10-26T00:00:00+02:00",
                "status": "ScheduleApplies"
            },
            "tomorrow": {
                "slots": [
                    {"start": 0, "end": 1440, "type": "NotPlanned"}
                ]
            },
            "updatedOn": "2026-10-26T01:38:50+00:00"
        }
    }

    # Test 1: During daytime at 10:15 (electricity is on)
    dt_day = datetime.datetime(2026, 10, 26, 10, 15, tzinfo=ZoneInfo("Europe/Kyiv"))
    res_day = get_facility_outage_schedule(fac, mock_raw, current_dt=dt_day)
    assert res_day["status"] == "NOT_PLANNED"
    assert "Світло є" in res_day["status_label"]
    assert res_day["next_outage"] is not None
    assert res_day["next_outage"]["start"] == "18:00"
    assert res_day["next_outage"]["type"] == "Probable"
    assert res_day["next_outage"]["minutes_until"] == (1080 - 615)  # 465 mins = 7 hr 45 min
    assert len(res_day["timeline_today"]) == 24
    assert res_day["timeline_today"][10]["is_current"] is True
    assert res_day["timeline_today"][10]["status"] == "NOT_PLANNED"
    assert res_day["timeline_today"][19]["status"] == "PROBABLE"
    assert res_day["timeline_today"][22]["status"] == "DEFINITE"

    # Test 2: During outage at 21:30 (definite outage)
    dt_night = datetime.datetime(2026, 10, 26, 21, 30, tzinfo=ZoneInfo("Europe/Kyiv"))
    res_night = get_facility_outage_schedule(fac, mock_raw, current_dt=dt_night)
    assert res_night["status"] == "DEFINITE"
    assert "Відключення" in res_night["status_label"]
    assert "до 24:00" in res_night["message"]


@pytest.mark.asyncio
async def test_check_and_notify_yasno_outages(db_session):
    # Setup test facility with YASNO enabled
    fac = Facility(
        name="Самар Виробництво",
        address="вул. Гетьманська, 5",
        yasno_enabled=True,
        yasno_group="3.2",
        yasno_region_id=3,
        yasno_dso_id=301
    )
    db_session.add(fac)
    await db_session.flush()

    # Clear sent alerts
    _SENT_YASNO_ALERTS.clear()

    # Suppose current time is 21:00, and next outage starts at 21:30 (30 mins until outage!)
    mock_raw = {
        "3.2": {
            "today": {
                "slots": [
                    {"start": 0, "end": 1290, "type": "NotPlanned"},  # 00:00 - 21:30
                    {"start": 1290, "end": 1440, "type": "Definite"}  # 21:30 - 24:00
                ]
            }
        }
    }

    with patch("backend.app.services.yasno_service.fetch_raw_yasno_schedule", new=AsyncMock(return_value=mock_raw)):
        with patch("backend.app.services.yasno_service.datetime") as mock_dt:
            # Fake current time at 21:02 Kyiv (28 minutes until 21:30)
            fake_now = datetime.datetime(2026, 10, 26, 21, 2, tzinfo=ZoneInfo("Europe/Kyiv"))
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.timezone = datetime.timezone

            with patch("backend.app.services.notification_service.send_push_notification", new=AsyncMock(return_value={"sent": 1})) as mock_push:
                dispatched = await check_and_notify_yasno_outages(db_session)
                assert len(dispatched) == 1
                assert dispatched[0]["slot"] == "21:30"
                mock_push.assert_called_once()
                call_args = mock_push.call_args[1]
                assert "21:30" in call_args["body"]
                assert "3.2" in call_args["title"]

                # Run a second time immediately - deduplication should prevent duplicate push!
                dispatched_again = await check_and_notify_yasno_outages(db_session)
                assert len(dispatched_again) == 0
                assert mock_push.call_count == 1  # Still 1, not called again
