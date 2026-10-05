import pytest


@pytest.mark.asyncio
async def test_maintenance_scheduled_vs_intermediate(client, superadmin_auth, operator_auth):
    # Setup generator: 1200 current hours, 300 interval, next_due at 1500
    await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор ТО",
            "model": "TO-300",
            "manufacturer": "PG",
            "serial_number": "SN-TO-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 1200.0,
            "initial_fuel_tank_level_l": 20.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )

    # Initial maintenance schedule status check
    sched_init = await client.get("/api/v1/maintenance/schedule", headers=operator_auth)
    assert sched_init.status_code == 200
    s_data = sched_init.json()
    assert s_data["current_operating_hours"] == 1200.0
    assert s_data["next_due_hours"] == 1500.0
    assert s_data["hours_remaining"] == 300.0

    # 1. Perform Intermediate maintenance at 1370 hours (e.g. spark plug replacement)
    # First, simulate generator running until 1370
    await client.post("/api/v1/generator/start", headers=operator_auth, json={})
    await client.post("/api/v1/generator/stop", headers=operator_auth, json={"end_hours": 1370.0})

    inter_res = await client.post(
        "/api/v1/maintenance/record",
        headers=operator_auth,
        json={
            "maintenance_type": "INTERMEDIATE",
            "work_description": "Заміна свічки запалювання та чистка повітряного фільтра",
            "consumables_used": "Свічка NGK BPR6ES - 1 шт",
            "cost": 350.0,
            "comment": "Планова проміжна заміна"
        }
    )
    assert inter_res.status_code == 201
    assert inter_res.json()["maintenance_type"] == "INTERMEDIATE"

    # CRITICAL RULE: Intermediate maintenance MUST NOT change next_due_hours (remains 1500)
    sched_after_inter = await client.get("/api/v1/maintenance/schedule", headers=operator_auth)
    assert sched_after_inter.status_code == 200
    s_inter = sched_after_inter.json()
    assert s_inter["current_operating_hours"] == 1370.0
    assert s_inter["next_due_hours"] == 1500.0  # Still 1500!
    assert s_inter["hours_remaining"] == 130.0  # 1500 - 1370

    # 2. Simulate running until 1505 hours (overdue)
    await client.post("/api/v1/generator/start", headers=operator_auth, json={})
    stop_overdue = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"end_hours": 1505.0}
    )
    assert stop_overdue.status_code == 200

    # Generator should now flag MAINTENANCE_REQUIRED
    gen_overdue = await client.get("/api/v1/generator", headers=operator_auth)
    assert gen_overdue.json()["status"] == "MAINTENANCE_REQUIRED"

    # 3. Perform Scheduled maintenance (Регламентне ТО)
    sched_record_res = await client.post(
        "/api/v1/maintenance/record",
        headers=operator_auth,
        json={
            "maintenance_type": "SCHEDULED",
            "work_description": "Регламентне ТО: заміна моторної оливи, масляного та повітряного фільтрів",
            "consumables_used": "Масло 10W-40 1.1л, фільтр",
            "cost": 1200.0
        }
    )
    assert sched_record_res.status_code == 201

    # Check that schedule advanced to 1505 + 300 = 1805 hours
    sched_final = await client.get("/api/v1/maintenance/schedule", headers=operator_auth)
    assert sched_final.status_code == 200
    s_final = sched_final.json()
    assert s_final["last_performed_hours"] == 1505.0
    assert s_final["next_due_hours"] == 1805.0

    # Generator status restored from MAINTENANCE_REQUIRED to STOPPED
    gen_final = await client.get("/api/v1/generator", headers=operator_auth)
    assert gen_final.json()["status"] == "STOPPED"


@pytest.mark.asyncio
async def test_maintenance_interval_alignment_and_seconds_duration(client, superadmin_auth, operator_auth):
    # User requirement: If we have 235 hours and maintenance norm is 300 hours, remaining should be 65 hours (next due 300)
    wizard_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Тест 235г",
            "model": "PG-6500",
            "manufacturer": "PowerGen",
            "serial_number": "SN-235",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.2,
            "initial_operating_hours": 235.0,
            "initial_fuel_tank_level_l": 20.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )
    assert wizard_res.status_code == 200

    sched_res = await client.get("/api/v1/maintenance/schedule", headers=operator_auth)
    assert sched_res.status_code == 200
    s_data = sched_res.json()
    assert s_data["current_operating_hours"] == 235.0
    assert s_data["next_due_hours"] == 300.0
    assert s_data["hours_remaining"] == 65.0  # Exactly 65 hours remaining!

    # Start generator
    start_res = await client.post("/api/v1/generator/start", headers=operator_auth, json={})
    assert start_res.status_code == 200

    # Stop without end_hours (simulating short run stopped by timer)
    stop_res = await client.post("/api/v1/generator/stop", headers=operator_auth, json={})
    assert stop_res.status_code == 200
    run_out = stop_res.json()
    assert run_out["duration_seconds"] is not None
    assert run_out["duration_seconds"] >= 1
    assert run_out["duration_formatted"] is not None
    assert run_out["calculated_consumption_l"] is not None
    # End hours should be approx 235.0 + small fraction
    assert run_out["end_hours"] >= 235.0
