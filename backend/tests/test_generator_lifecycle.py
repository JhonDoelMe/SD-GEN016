import pytest


@pytest.mark.asyncio
async def test_generator_wizard_and_lifecycle(client, superadmin_auth, operator_auth):
    # 1. Attempt start before wizard configuration -> rejected
    unconf_start = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={}
    )
    assert unconf_start.status_code == 400
    assert "налаштований" in unconf_start.json()["detail"]

    # 2. Run Wizard setup
    wizard_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Бензогенератор об'єкта 5.5 кВт",
            "model": "K&S Basic KSB 6000",
            "manufacturer": "K&S",
            "serial_number": "SN-9874521",
            "rated_power_kw": 5.5,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.2,
            "initial_operating_hours": 100.0,
            "initial_fuel_tank_level_l": 15.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )
    assert wizard_res.status_code == 200
    gen_data = wizard_res.json()
    assert gen_data["is_configured"] is True
    assert gen_data["current_operating_hours"] == 100.0
    assert gen_data["fuel_tank_level_l"] == 15.0
    assert gen_data["status"] == "STOPPED"

    # 3. Start generator by operator
    start_res = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"fuel_level_l": 15.0}
    )
    assert start_res.status_code == 200
    run_data = start_res.json()
    assert run_data["status"] == "RUNNING"
    assert run_data["start_hours"] == 100.0

    # 4. Invariant: cannot start already running generator
    start_again = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={}
    )
    assert start_again.status_code == 400
    assert "працює" in start_again.json()["detail"]

    # 5. Invariant: cannot stop with end_hours < start_hours
    stop_invalid = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"end_hours": 95.0}
    )
    assert stop_invalid.status_code == 400
    assert "не можуть бути меншими" in stop_invalid.json()["detail"]

    # 6. Stop generator properly with 103.5 hours
    stop_res = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"end_hours": 103.5, "note": "Планова зупинка"}
    )
    assert stop_res.status_code == 200
    stop_data = stop_res.json()
    assert stop_data["status"] == "COMPLETED"
    assert stop_data["duration_hours"] == 3.5
    # consumption = 3.5 * 2.2 = 7.7 liters
    assert stop_data["calculated_consumption_l"] == 7.7
    assert stop_data["end_hours"] == 103.5

    # Check generator state after stop
    gen_after = await client.get("/api/v1/generator", headers=operator_auth)
    assert gen_after.status_code == 200
    g = gen_after.json()
    assert g["status"] == "STOPPED"
    assert g["current_operating_hours"] == 103.5
    # Tank level was 15.0 - 7.7 = 7.3 liters
    assert round(g["fuel_tank_level_l"], 1) == 7.3

    # 7. Invariant: cannot stop already stopped generator
    stop_again = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"end_hours": 105.0}
    )
    assert stop_again.status_code == 400
    assert "не перебуває у стані 'Працює'" in stop_again.json()["detail"]
