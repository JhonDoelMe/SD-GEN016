import pytest


@pytest.mark.asyncio
async def test_fault_lifecycle_and_generator_safety(client, superadmin_auth, operator_auth):
    # Setup generator
    gen_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Дефектів",
            "model": "D-1",
            "manufacturer": "PG",
            "serial_number": "SN-FAULT-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 10.0,
            "initial_fuel_tank_level_l": 10.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )
    gen_id = gen_res.json()["id"]

    # 1. Report CRITICAL fault: "Витік палива з паливопроводу"
    fault_res = await client.post(
        "/api/v1/faults",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "title": "Витік бензину з паливопроводу",
            "description": "Пошкодження шланга подачі бензину біля карбюратора",
            "priority": "CRITICAL"
        }
    )
    assert fault_res.status_code == 201
    fault_id = fault_res.json()["id"]
    assert fault_res.json()["status"] == "NEW"

    # Generator status should become FAULTY
    gen_check = await client.get("/api/v1/generator", headers=operator_auth)
    assert gen_check.json()["status"] == "FAULTY"

    # Invariant: starting a faulty generator is blocked!
    start_try = await client.post("/api/v1/generator/start", headers=operator_auth, json={})
    assert start_try.status_code == 400
    assert "має критичну несправність" in start_try.json()["detail"]

    # 2. Advance fault lifecycle: IN_PROGRESS -> RESOLVED
    await client.put(
        f"/api/v1/faults/{fault_id}/status",
        headers=superadmin_auth,
        json={"status": "IN_PROGRESS"}
    )

    resolve_res = await client.put(
        f"/api/v1/faults/{fault_id}/status",
        headers=superadmin_auth,
        json={
            "status": "RESOLVED",
            "resolution_notes": "Замінено паливний шланг та затискний хомут. Герметичність перевірена."
        }
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "RESOLVED"

    # Generator status should now be restored to STOPPED
    gen_restored = await client.get("/api/v1/generator", headers=operator_auth)
    assert gen_restored.json()["status"] == "STOPPED"


@pytest.mark.asyncio
async def test_operational_reports_and_csv_export(client, superadmin_auth):
    # Fetch summary
    rep_res = await client.get("/api/v1/reports/summary", headers=superadmin_auth)
    assert rep_res.status_code == 200
    rep_data = rep_res.json()
    assert "total_operating_hours" in rep_data
    assert "total_fuel_received_l" in rep_data

    # Fetch CSV export
    csv_res = await client.get("/api/v1/reports/export", headers=superadmin_auth)
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert "Параметр" in csv_res.text
