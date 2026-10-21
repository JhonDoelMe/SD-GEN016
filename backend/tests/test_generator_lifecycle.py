import pytest


@pytest.mark.asyncio
async def test_generator_wizard_and_lifecycle(client, superadmin_auth, operator_auth):
    # 1. Verify default generator is initialized and configured on clean start
    init_res = await client.get(
        "/api/v1/generator",
        headers=operator_auth
    )
    assert init_res.status_code == 200
    assert init_res.json()["is_configured"] is True

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



@pytest.mark.asyncio
async def test_generator_manual_run_entry(client, superadmin_auth, operator_auth):
    # Setup generator with 10.0 hours and 20.0 L fuel
    gen_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Ручний Запис",
            "model": "M-100",
            "manufacturer": "PG",
            "serial_number": "SN-MANUAL-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 10.0,
            "initial_fuel_tank_level_l": 20.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )
    assert gen_res.status_code == 200
    gen_id = gen_res.json()["id"]

    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    start_time = (now - datetime.timedelta(hours=3)).isoformat()
    end_time = (now - datetime.timedelta(hours=1)).isoformat()

    # 1. Validation: start_time >= end_time is rejected
    invalid_res = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": end_time,
            "end_time": start_time,
            "note": "Помилковий час"
        }
    )
    assert invalid_res.status_code == 400
    assert "Час завершення" in invalid_res.json()["detail"]

    # 2. Valid manual entry (2.0 hours run)
    valid_res = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": start_time,
            "end_time": end_time,
            "start_hours": 10.0,
            "end_hours": 12.0,
            "note": "Запис з паперового журналу через блекаут"
        }
    )
    assert valid_res.status_code == 201
    run_data = valid_res.json()
    assert run_data["status"] == "COMPLETED"
    assert run_data["start_hours"] == 10.0
    assert run_data["end_hours"] == 12.0
    assert run_data["duration_hours"] == 2.0
    # consumption = 2.0 * 2.0 l/h = 4.0 liters
    assert run_data["calculated_consumption_l"] == 4.0
    assert "блекаут" in run_data["note"]

    # 3. Generator state updated properly
    gen_after = await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=operator_auth)
    g = gen_after.json()
    assert g["current_operating_hours"] == 12.0
    assert g["fuel_tank_level_l"] == 16.0  # 20.0 - 4.0 = 16.0 L

    # 4. Check runs history
    runs_res = await client.get(f"/api/v1/generator/runs?generator_id={gen_id}", headers=operator_auth)
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert len(runs) >= 1
    assert any(r["id"] == run_data["id"] for r in runs)

    # 5. Check audit log
    audit_res = await client.get("/api/v1/audit?limit=10", headers=superadmin_auth)
    assert audit_res.status_code == 200
    actions = [a["action"] for a in audit_res.json()]
    assert "GENERATOR_MANUAL_RUN_ADDED" in actions


@pytest.mark.asyncio
async def test_generator_fuel_deficit_goes_negative(client, superadmin_auth, operator_auth):
    """Перевірка того, що при перевитраті палива бак іде в мінус, а не обрізається до 0.0"""
    # 1. Fetch generator
    gen_res = await client.get("/api/v1/generator", headers=superadmin_auth)
    assert gen_res.status_code == 200
    gen_id = gen_res.json()["id"]

    # Set fuel to 5.0 L via adjustment
    await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "Generator",
            "entity_id": gen_id,
            "field_name": "fuel_tank_level_l",
            "new_value": "5.0",
            "reason": "Встановлення низького рівня для перевірки дефіциту"
        }
    )

    # 2. Add manual run consuming 10.0 L (deficit: 5.0 - 10.0 = -5.0 L)
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    start_time = (now - datetime.timedelta(hours=6)).isoformat()
    end_time = (now - datetime.timedelta(hours=1)).isoformat()

    manual_res = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": start_time,
            "end_time": end_time,
            "start_hours": 100.0,
            "end_hours": 105.0,
            "fuel_consumed_l": 10.0,
            "note": "Робота довше за залишок у баку"
        }
    )
    assert manual_res.status_code == 201
    run_data = manual_res.json()
    assert run_data["end_fuel_level_l"] == -5.0

    # 3. Check generator state
    gen_after = await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=operator_auth)
    assert gen_after.status_code == 200
    assert gen_after.json()["fuel_tank_level_l"] == -5.0
