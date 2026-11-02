import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_initial_facility_yasno_disabled_by_default(client, superadmin_auth):
    # Initial seeded facility (id=1) MUST NOT have YASNO enabled or hardcoded group 3.2
    facs_res = await client.get("/api/v1/facilities", headers=superadmin_auth)
    assert facs_res.status_code == 200
    facs = facs_res.json()
    default_fac = next(f for f in facs if f["id"] == 1)
    assert default_fac["yasno_enabled"] is False
    assert default_fac["yasno_group"] is None

    sched_res = await client.get("/api/v1/facilities/1/outage-schedule", headers=superadmin_auth)
    assert sched_res.status_code == 200
    sched_data = sched_res.json()
    assert sched_data["enabled"] is False
    assert sched_data["status"] == "DISABLED"


@pytest.mark.asyncio
async def test_facility_yasno_configuration_and_schedule_api(client, superadmin_auth):
    # 1. Create facility with YASNO monitoring enabled
    create_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={
            "name": "Об'єкт Самар (Новомосковськ)",
            "address": "вул. Гетьманська, 12",
            "description": "Базовий вузол зв'язку",
            "timezone": "Europe/Kyiv",
            "yasno_enabled": True,
            "yasno_region_id": 3,
            "yasno_dso_id": 301,
            "yasno_group": "3.2"
        }
    )
    assert create_res.status_code == 201
    fac = create_res.json()
    fac_id = fac["id"]
    assert fac["yasno_enabled"] is True
    assert fac["yasno_group"] == "3.2"
    assert fac["yasno_dso_id"] == 301

    # 2. Mock raw YASNO schedule response
    mock_raw = {
        "3.2": {
            "today": {
                "slots": [
                    {"start": 0, "end": 1290, "type": "NotPlanned"},
                    {"start": 1290, "end": 1440, "type": "Definite"}
                ]
            },
            "tomorrow": {
                "slots": [
                    {"start": 0, "end": 1440, "type": "NotPlanned"}
                ]
            },
            "updatedOn": "2026-10-26T01:38:50+00:00"
        }
    }

    with patch("backend.app.api.v1.facilities.fetch_raw_yasno_schedule", new=AsyncMock(return_value=mock_raw)):
        # 3. Request outage schedule endpoint
        sched_res = await client.get(f"/api/v1/facilities/{fac_id}/outage-schedule", headers=superadmin_auth)
        assert sched_res.status_code == 200
        data = sched_res.json()

        assert data["facility_id"] == fac_id
        assert data["group"] == "3.2"
        assert data["enabled"] is True
        assert data["dso_name"] == "ДТЕК Дніпровські електромережі (ДнЕМ)"
        assert len(data["timeline_today"]) == 24
        assert data["timeline_today"][22]["status"] == "DEFINITE"

    # 4. Update facility - change group to 4.1
    update_res = await client.put(
        f"/api/v1/facilities/{fac_id}",
        headers=superadmin_auth,
        json={"yasno_group": "4.1"}
    )
    assert update_res.status_code == 200
    updated_fac = update_res.json()
    assert updated_fac["yasno_group"] == "4.1"
