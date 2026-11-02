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
    _is_cached_schedule_current_day,
    _SENT_YASNO_ALERTS,
    _YASNO_ALERT_ATTEMPTS,
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

                # Simulate container restart (clear in-memory set) - DB NotificationLog must still prevent duplicate!
                _SENT_YASNO_ALERTS.clear()
                _YASNO_ALERT_ATTEMPTS.clear()
                dispatched_after_restart = await check_and_notify_yasno_outages(db_session)
                assert len(dispatched_after_restart) == 0
                assert mock_push.call_count == 1


@pytest.mark.asyncio
async def test_yasno_push_retry_on_zero_sent_and_bounded_attempts(db_session):
    fac = Facility(
        name="Самар Склад",
        address="вул. Центральна, 10",
        yasno_enabled=True,
        yasno_group="4.1",
        yasno_region_id=3,
        yasno_dso_id=301
    )
    db_session.add(fac)
    await db_session.flush()

    _SENT_YASNO_ALERTS.clear()
    _YASNO_ALERT_ATTEMPTS.clear()

    mock_raw = {
        "4.1": {
            "today": {
                "slots": [
                    {"start": 0, "end": 900, "type": "NotPlanned"},   # 00:00 - 15:00
                    {"start": 900, "end": 1080, "type": "Definite"}   # 15:00 - 18:00
                ]
            }
        }
    }

    with patch("backend.app.services.yasno_service.fetch_raw_yasno_schedule", new=AsyncMock(return_value=mock_raw)):
        with patch("backend.app.services.yasno_service.datetime") as mock_dt:
            fake_now = datetime.datetime(2026, 10, 26, 14, 30, tzinfo=ZoneInfo("Europe/Kyiv"))
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.timezone = datetime.timezone

            # 1st attempt fails (sent=0) -> should NOT permanently lock the alert slot
            with patch(
                "backend.app.services.notification_service.send_push_notification",
                new=AsyncMock(side_effect=[{"sent": 0, "failed": 1}, {"sent": 2, "failed": 0}])
            ) as mock_push:
                res1 = await check_and_notify_yasno_outages(db_session)
                assert len(res1) == 0
                assert mock_push.call_count == 1

                # 2nd attempt retries and succeeds (sent=2)
                res2 = await check_and_notify_yasno_outages(db_session)
                assert len(res2) == 1
                assert res2[0]["slot"] == "15:00"
                assert mock_push.call_count == 2

                # 3rd call does not send again because 2nd attempt succeeded
                res3 = await check_and_notify_yasno_outages(db_session)
                assert len(res3) == 0
                assert mock_push.call_count == 2



def test_midnight_rollover_and_tomorrow_timeline_red_marks():
    fac = Facility(id=1, name="Х016 (Перемоги 32)", yasno_enabled=True, yasno_group="3.2", yasno_region_id=3, yasno_dso_id=301)

    # Pre-midnight YASNO payload where 'today' is Nov 2 (no outages) and 'tomorrow' is Nov 3 (18:30 - 22:00 Definite)
    pre_midnight_raw = {
        "3.2": {
            "today": {
                "slots": [
                    {"start": 0, "end": 1440, "type": "NotPlanned"}
                ],
                "date": "2026-11-02T00:00:00+02:00",
                "status": "ScheduleApplies"
            },
            "tomorrow": {
                "slots": [
                    {"start": 0, "end": 1110, "type": "NotPlanned"},      # 00:00 - 18:30
                    {"start": 1110, "end": 1320, "type": "Definite"},     # 18:30 - 22:00 (red)
                    {"start": 1320, "end": 1440, "type": "NotPlanned"}    # 22:00 - 24:00
                ],
                "date": "2026-11-03T00:00:00+02:00",
                "status": "ScheduleApplies"
            },
            "updatedOn": "2026-11-02T20:02:23+00:00"
        }
    }

    # Case A: Before midnight (Nov 2 at 22:05) -> next outage is tomorrow, timeline_tomorrow has red hours 18..21, timeline_day == 'tomorrow'
    dt_before_midnight = datetime.datetime(2026, 11, 2, 22, 5, tzinfo=ZoneInfo("Europe/Kyiv"))
    res_before = get_facility_outage_schedule(fac, pre_midnight_raw, current_dt=dt_before_midnight)
    assert res_before["next_outage"]["day"] == "tomorrow"
    assert res_before["next_outage"]["start"] == "18:30"
    assert res_before["next_outage"]["end"] == "22:00"
    assert res_before["timeline_day"] == "tomorrow"
    assert len(res_before["timeline_tomorrow"]) == 24
    for h in (18, 19, 20, 21):
        assert res_before["timeline_tomorrow"][h]["status"] == "DEFINITE"
    assert res_before["timeline_tomorrow"][17]["status"] == "NOT_PLANNED"
    assert res_before["timeline_tomorrow"][22]["status"] == "NOT_PLANNED"
    assert _is_cached_schedule_current_day(pre_midnight_raw, "2026-11-02") is True

    # Case B: After midnight (Nov 3 at 00:03) with pre-midnight payload -> must shift 'tomorrow' (Nov 3) into 'today'!
    dt_after_midnight = datetime.datetime(2026, 11, 3, 0, 3, tzinfo=ZoneInfo("Europe/Kyiv"))
    res_after = get_facility_outage_schedule(fac, pre_midnight_raw, current_dt=dt_after_midnight)
    assert res_after["next_outage"]["day"] == "today"
    assert res_after["next_outage"]["start"] == "18:30"
    assert res_after["next_outage"]["end"] == "22:00"
    assert res_after["next_outage"]["minutes_until"] == 1107  # 18 hr 27 min (NOT 42 hr 27 min)
    assert res_after["next_outage"]["human_until"] == "18 год 27 хв"
    assert res_after["timeline_day"] == "today"
    for h in (18, 19, 20, 21):
        assert res_after["timeline_today"][h]["status"] == "DEFINITE"
    assert res_after["timeline_today"][0]["is_current"] is True
    assert _is_cached_schedule_current_day(pre_midnight_raw, "2026-11-03") is False
