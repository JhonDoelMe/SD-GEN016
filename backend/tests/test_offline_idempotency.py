import pytest


@pytest.mark.asyncio
async def test_stop_generator_idempotency_key_and_conflict(client, superadmin_auth, operator_auth):
    fac_id = (await client.get("/api/v1/facilities", headers=superadmin_auth)).json()[0]["id"]
    gen_res = await client.post(
        "/api/v1/generator",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "name": "Офлайн-Тест Ген",
            "model": "OF-5000",
            "manufacturer": "Test",
            "serial_number": "OF-SN-001",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 10.0,
            "initial_fuel_tank_level_l": 20.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert gen_res.status_code == 201, gen_res.text
    gen_id = gen_res.json()["id"]

    start_res = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "fuel_level_l": 20.0, "idempotency_key": "OF-START-1"},
    )
    assert start_res.status_code == 200, start_res.text

    stop_payload = {
        "generator_id": gen_id,
        "end_hours": 10.5,
        "note": "Зупинка в офлайн-черзі",
        "idempotency_key": "OF-STOP-1",
    }
    stop1 = await client.post("/api/v1/generator/stop", headers=operator_auth, json=stop_payload)
    assert stop1.status_code == 200, stop1.text
    run1 = stop1.json()
    assert run1["status"] == "COMPLETED"
    assert run1["end_hours"] == pytest.approx(10.5)

    # Exact replay with same idempotency_key when generator is already STOPPED -> replays 200 without 400 error
    stop2 = await client.post("/api/v1/generator/stop", headers=operator_auth, json=stop_payload)
    assert stop2.status_code == 200, stop2.text
    assert stop2.headers.get("X-Idempotency-Replayed") == "true"
    assert stop2.json()["id"] == run1["id"]

    # Same idempotency_key with different parameters -> 409 Conflict
    stop_mismatch = {**stop_payload, "note": "Змінена примітка"}
    conflict = await client.post("/api/v1/generator/stop", headers=operator_auth, json=stop_mismatch)
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_canister_dispatch_return_and_receive_idempotency(client, superadmin_auth, operator_auth):
    fac_id = (await client.get("/api/v1/facilities", headers=superadmin_auth)).json()[0]["id"]
    stock_id = (await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)).json()[0]["id"]

    pool_res = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "name": "Офлайн Каністри",
            "canister_volume_l": 20.0,
            "full_count": 2,
            "empty_count": 3,
            "away_refill_count": 0,
            "reserve_liters": 0.0,
        },
    )
    assert pool_res.status_code == 201, pool_res.text
    pool_id = pool_res.json()["id"]

    # 1. Dispatch 2 via header Idempotency-Key -> replay doesn't deduct 2 more
    d1 = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/dispatch",
        headers={**operator_auth, "Idempotency-Key": "OF-DISP-1"},
        json={"count": 2, "comment": "На заправку"},
    )
    assert d1.status_code == 200, d1.text
    assert d1.json()["empty_count"] == 1
    assert d1.json()["away_refill_count"] == 2

    d2 = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/dispatch",
        headers={**operator_auth, "Idempotency-Key": "OF-DISP-1"},
        json={"count": 2, "comment": "На заправку"},
    )
    assert d2.status_code == 200
    assert d2.headers.get("X-Idempotency-Replayed") == "true"
    assert d2.json()["empty_count"] == 1
    assert d2.json()["away_refill_count"] == 2

    # 2. Return 1 empty via payload idempotency_key
    ret_body = {"count": 1, "comment": "Не заправили", "idempotency_key": "OF-RET-1"}
    r1 = await client.post(f"/api/v1/fuel/canisters/{pool_id}/return-empty", headers=operator_auth, json=ret_body)
    assert r1.status_code == 200, r1.text
    assert r1.json()["away_refill_count"] == 1
    assert r1.json()["empty_count"] == 2

    r2 = await client.post(f"/api/v1/fuel/canisters/{pool_id}/return-empty", headers=operator_auth, json=ret_body)
    assert r2.status_code == 200
    assert r2.headers.get("X-Idempotency-Replayed") == "true"
    assert r2.json()["away_refill_count"] == 1

    # 3. Receive 2 refilled (create_receipt=False + idempotency_key) -> replay does not double-add
    rec_body = {
        "count": 2,
        "source": "auto",
        "create_receipt": False,
        "driver_name": "Водій Тест",
        "idempotency_key": "OF-REC-NORECEIPT",
    }
    p1 = await client.post(f"/api/v1/fuel/canisters/{pool_id}/receive", headers=operator_auth, json=rec_body)
    assert p1.status_code == 200, p1.text
    assert p1.json()["full_count"] == 4
    assert p1.json()["away_refill_count"] == 0
    assert p1.json()["empty_count"] == 1

    p2 = await client.post(f"/api/v1/fuel/canisters/{pool_id}/receive", headers=operator_auth, json=rec_body)
    assert p2.status_code == 200
    assert p2.headers.get("X-Idempotency-Replayed") == "true"
    assert p2.json()["full_count"] == 4

    # 4. Receive remaining 1 with create_receipt=True -> replay produces only 1 receipt
    rec_with_rcpt = {
        "count": 1,
        "source": "auto",
        "create_receipt": True,
        "gas_station_name": "АЗК WOG",
        "driver_name": "Водій Тест",
        "receipt_number": "CHK-OF-01",
        "idempotency_key": "OF-REC-RCPT",
    }
    p3 = await client.post(f"/api/v1/fuel/canisters/{pool_id}/receive", headers=operator_auth, json=rec_with_rcpt)
    assert p3.status_code == 200, p3.text
    assert p3.json()["full_count"] == 5

    p4 = await client.post(f"/api/v1/fuel/canisters/{pool_id}/receive", headers=operator_auth, json=rec_with_rcpt)
    assert p4.status_code == 200
    assert p4.headers.get("X-Idempotency-Replayed") == "true"

    receipts = (await client.get(f"/api/v1/fuel/receipts?facility_id={fac_id}", headers=superadmin_auth)).json()
    assert len([r for r in receipts if r["receipt_number"] == "CHK-OF-01"]) == 1


@pytest.mark.asyncio
async def test_maintenance_and_fault_idempotency(client, superadmin_auth, operator_auth):
    fac_id = (await client.get("/api/v1/facilities", headers=superadmin_auth)).json()[0]["id"]
    gen_res = await client.post(
        "/api/v1/generator",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "name": "ТО-Офлайн Ген",
            "model": "MF-100",
            "manufacturer": "Test",
            "serial_number": "MF-SN-001",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 100.0,
            "initial_fuel_tank_level_l": 10.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert gen_res.status_code == 201
    gen_id = gen_res.json()["id"]

    maint_payload = {
        "generator_id": gen_id,
        "maintenance_type": "INTERMEDIATE",
        "work_description": "Перевірка рівня масла та фільтра",
        "cost": 150.0,
        "idempotency_key": "OF-MAINT-1",
    }
    m1 = await client.post("/api/v1/maintenance/record", headers=operator_auth, json=maint_payload)
    assert m1.status_code == 201, m1.text
    m2 = await client.post("/api/v1/maintenance/record", headers=operator_auth, json=maint_payload)
    assert m2.status_code == 201
    assert m2.headers.get("X-Idempotency-Replayed") == "true"
    assert m2.json()["id"] == m1.json()["id"]

    recs = (await client.get(f"/api/v1/maintenance/records?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert len(recs) == 1

    fault_payload = {
        "generator_id": gen_id,
        "title": "Підтікання паливного крана",
        "description": "Помічено незначне підтікання під час запуску",
        "priority": "MEDIUM",
        "idempotency_key": "OF-FAULT-1",
    }
    f1 = await client.post("/api/v1/faults", headers=operator_auth, json=fault_payload)
    assert f1.status_code == 201, f1.text
    f2 = await client.post("/api/v1/faults", headers=operator_auth, json=fault_payload)
    assert f2.status_code == 201
    assert f2.headers.get("X-Idempotency-Replayed") == "true"
    assert f2.json()["id"] == f1.json()["id"]

    faults = (await client.get(f"/api/v1/faults?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert len(faults) == 1
