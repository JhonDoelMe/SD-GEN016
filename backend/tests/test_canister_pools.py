import pytest


@pytest.mark.asyncio
async def test_canister_pool_reserve_first_and_dispatch_receive_flow(client, superadmin_auth, operator_auth):
    # Setup facility generator & stock
    fac_res = await client.get("/api/v1/facilities", headers=superadmin_auth)
    assert fac_res.status_code == 200
    fac_id = fac_res.json()[0]["id"]

    # Configure generator with 30L tank so 24L transfer fits in one go
    gen_res = await client.post(
        "/api/v1/generator",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "name": "Тест-Ген 30л",
            "model": "PG-9000",
            "manufacturer": "Test",
            "serial_number": "CAN-GEN-01",
            "rated_power_kw": 7.5,
            "tank_capacity_l": 30.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.5,
            "initial_operating_hours": 0.0,
            "initial_fuel_tank_level_l": 0.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert gen_res.status_code == 201, gen_res.text
    gen_id = gen_res.json()["id"]

    stocks_res = await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)
    assert stocks_res.status_code == 200
    stock_id = stocks_res.json()[0]["id"]

    # Operator must NOT be able to create canister pools (fuel:configure required)
    op_create = await client.post(
        "/api/v1/fuel/canisters",
        headers=operator_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "name": "Каністри 20л",
            "canister_volume_l": 20.0,
            "full_count": 5,
            "empty_count": 0,
            "away_refill_count": 0,
            "reserve_liters": 0.0,
        },
    )
    assert op_create.status_code == 403

    # SuperAdmin creates 5 x 20L canister pool (all 5 full -> 100L)
    pool_res = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "name": "Каністри 20л (А-95)",
            "canister_volume_l": 20.0,
            "full_count": 5,
            "empty_count": 0,
            "away_refill_count": 0,
            "reserve_liters": 0.0,
        },
    )
    assert pool_res.status_code == 201, pool_res.text
    pool = pool_res.json()
    pool_id = pool["id"]
    assert pool["total_count"] == 5
    assert pool["full_count"] == 5
    assert pool["available_liters"] == pytest.approx(100.0)

    # Stock balance auto-synced to 100L + summary includes canister breakdown
    summary1 = (await client.get(f"/api/v1/fuel/summary?facility_id={fac_id}", headers=superadmin_auth)).json()
    assert summary1["warehouse_balance_l"] == pytest.approx(100.0)
    assert summary1["canisters_total"] == 5
    assert summary1["canisters_full"] == 5

    # 1. Operator transfers 16L -> opens 1 canister, puts 4L into on-site reserve, canister becomes EMPTY
    tr1 = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 16.0},
    )
    assert tr1.status_code == 201, tr1.text
    tr1_data = tr1.json()
    assert tr1_data["used_from_reserve_l"] == pytest.approx(0.0)
    assert tr1_data["opened_canisters_count"] == 1
    assert tr1_data["canister_reserve_after_l"] == pytest.approx(4.0)
    assert tr1_data["source_balance_after"] == pytest.approx(84.0)

    # 2. Dispatch that 1 empty canister for refilling
    disp1 = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/dispatch",
        headers=operator_auth,
        json={"count": 1, "comment": "Поїхала на WOG"},
    )
    assert disp1.status_code == 200, disp1.text
    assert disp1.json()["empty_count"] == 0
    assert disp1.json()["away_refill_count"] == 1

    # Dispatching another empty canister when empty_count==0 must fail cleanly
    disp_err = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/dispatch",
        headers=operator_auth,
        json={"count": 1},
    )
    assert disp_err.status_code == 400

    # Reset generator tank level to 0 (simulate consumption) by creating a fresh generator transfer target or adjusting tank
    adj_res = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "entity_type": "Generator",
            "entity_id": gen_id,
            "field_name": "fuel_tank_level_l",
            "new_value": "0",
            "reason": "Тестова імітація витрати бака",
        },
    )
    assert adj_res.status_code == 201, adj_res.text

    # 3. User's exact example: transfer 24L when reserve has 4L!
    # Must consume 4L from reserve FIRST + open 1 x 20L canister, leaving reserve=0.0, full=3, empty=1, away=1 (60L total)
    tr2 = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 24.0},
    )
    assert tr2.status_code == 201, tr2.text
    tr2_data = tr2.json()
    assert tr2_data["used_from_reserve_l"] == pytest.approx(4.0)
    assert tr2_data["opened_canisters_count"] == 1
    assert tr2_data["canister_reserve_after_l"] == pytest.approx(0.0)
    assert tr2_data["source_balance_after"] == pytest.approx(60.0)

    # 4. Transfer 5L (opens 1 canister -> reserve becomes 15L, full=2, empty=2)
    adj_res2 = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "entity_type": "Generator",
            "entity_id": gen_id,
            "field_name": "fuel_tank_level_l",
            "new_value": "0",
            "reason": "Скидання для перевірки чистого резерву",
        },
    )
    assert adj_res2.status_code == 201
    tr3 = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 5.0},
    )
    assert tr3.status_code == 201
    assert tr3.json()["opened_canisters_count"] == 1
    assert tr3.json()["canister_reserve_after_l"] == pytest.approx(15.0)

    # 5. Transfer 4L (< reserve 15L) -> uses reserve ONLY (0 canisters opened, reserve=11L!)
    tr4 = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 4.0},
    )
    assert tr4.status_code == 201
    assert tr4.json()["used_from_reserve_l"] == pytest.approx(4.0)
    assert tr4.json()["opened_canisters_count"] == 0
    assert tr4.json()["canister_reserve_after_l"] == pytest.approx(11.0)

    # 6. Bring back the 1 dispatched canister refilled (create_receipt=True) -> full=3, away=0, stock +20L
    rec1 = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/receive",
        headers=operator_auth,
        json={"count": 1, "source": "away", "create_receipt": True, "driver_name": "Петренко В.В."},
    )
    assert rec1.status_code == 200, rec1.text
    p_after = rec1.json()
    assert p_after["away_refill_count"] == 0
    assert p_after["full_count"] == 3
    assert p_after["empty_count"] == 2
    assert p_after["reserve_liters"] == pytest.approx(11.0)
    assert p_after["available_liters"] == pytest.approx(71.0)

    # Check transactions log contains CONSUME_TRANSFER, DISPATCH_REFILL, RECEIVE_REFILL
    txs_res = await client.get(f"/api/v1/fuel/canisters/transactions?facility_id={fac_id}", headers=superadmin_auth)
    assert txs_res.status_code == 200
    ops = [t["operation"] for t in txs_res.json()]
    assert "CONSUME_TRANSFER" in ops
    assert "DISPATCH_REFILL" in ops
    assert "RECEIVE_REFILL" in ops


@pytest.mark.asyncio
async def test_canister_pool_validations_and_return_empty(client, superadmin_auth, operator_auth):
    fac_id = (await client.get("/api/v1/facilities", headers=superadmin_auth)).json()[0]["id"]
    stock_id = (await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)).json()[0]["id"]

    # Reject reserve >= canister volume
    bad_pool = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "name": "Некоректний резерв",
            "canister_volume_l": 20.0,
            "full_count": 2,
            "empty_count": 1,
            "away_refill_count": 0,
            "reserve_liters": 20.0,
        },
    )
    assert bad_pool.status_code == 400

    # Create valid pool with 2 empty canisters
    ok_pool = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "name": "Пул ДП",
            "canister_volume_l": 20.0,
            "full_count": 0,
            "empty_count": 2,
            "away_refill_count": 0,
            "reserve_liters": 0.0,
        },
    )
    assert ok_pool.status_code == 201
    pool_id = ok_pool.json()["id"]

    # Dispatch 2, return 1 unfilled, direct receipt 15L (non-multiple) must be rejected on canister stock
    await client.post(f"/api/v1/fuel/canisters/{pool_id}/dispatch", headers=operator_auth, json={"count": 2})
    ret1 = await client.post(f"/api/v1/fuel/canisters/{pool_id}/return-empty", headers=operator_auth, json={"count": 1})
    assert ret1.status_code == 200
    assert ret1.json()["away_refill_count"] == 1
    assert ret1.json()["empty_count"] == 1

    non_mult = await client.post(
        "/api/v1/fuel/receipt",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "liters": 15.0,
            "driver_name": "Водій Тест",
            "receipt_number": "CHK-ERR-15",
        },
    )
    assert non_mult.status_code == 400

    # Deleting empty pool succeeds
    del_res = await client.delete(f"/api/v1/fuel/canisters/{pool_id}", headers=superadmin_auth)
    assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_canister_pool_backup_restore_and_facility_clean(client, superadmin_auth, operator_auth):
    fac_id = (await client.get("/api/v1/facilities", headers=superadmin_auth)).json()[0]["id"]
    stock_id = (await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)).json()[0]["id"]

    pool_res = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "name": "Каністри для бекапу",
            "canister_volume_l": 20.0,
            "full_count": 3,
            "empty_count": 1,
            "away_refill_count": 1,
            "reserve_liters": 2.5,
        },
    )
    assert pool_res.status_code == 201
    pool_id = pool_res.json()["id"]

    # Create backup and restore cleanly
    bak = await client.post("/api/v1/backups", headers=superadmin_auth, json={"backup_type": "partial", "notes": "Canister test"})
    assert bak.status_code == 201, bak.text
    fname = bak.json()["filename"]

    rest = await client.post(
        f"/api/v1/backups/{fname}/restore",
        headers=superadmin_auth,
        json={"confirmation": "ВІДНОВИТИ", "restore_files": False},
    )
    assert rest.status_code == 200, rest.text
    safety_fname = rest.json().get("safety_backup_filename")

    after = (await client.get(f"/api/v1/fuel/canisters?facility_id={fac_id}", headers=superadmin_auth)).json()
    assert len(after) == 1
    assert after[0]["id"] == pool_id
    assert after[0]["full_count"] == 3
    assert after[0]["reserve_liters"] == pytest.approx(2.5)

    await client.delete(f"/api/v1/backups/{fname}", headers=superadmin_auth)
    if safety_fname:
        await client.delete(f"/api/v1/backups/{safety_fname}", headers=superadmin_auth)

    # facility_clean zeroes full/away/reserve and sets all canisters empty
    from backend.app.config import settings
    clean_res = await client.post(
        "/api/v1/system/reset",
        headers=superadmin_auth,
        json={
            "mode": "facility_clean",
            "facility_id": fac_id,
            "confirm_code": "ОЧИСТИТИ",
            "admin_password": settings.INITIAL_ADMIN_PASSWORD,
        },
    )
    assert clean_res.status_code == 200, clean_res.text

    after_clean = (await client.get(f"/api/v1/fuel/canisters?facility_id={fac_id}", headers=superadmin_auth)).json()[0]
    assert after_clean["full_count"] == 0
    assert after_clean["away_refill_count"] == 0
    assert after_clean["empty_count"] == 5
    assert after_clean["reserve_liters"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_canister_receive_auto_source_order(client, superadmin_auth, operator_auth):
    fac_id = (await client.get("/api/v1/facilities", headers=superadmin_auth)).json()[0]["id"]
    stock_id = (await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)).json()[0]["id"]

    # Pool: 5 x 20L -> 1 full, 2 empty, 2 away at gas station
    pool_res = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "name": "Каністри Авто-Прийом",
            "canister_volume_l": 20.0,
            "full_count": 1,
            "empty_count": 2,
            "away_refill_count": 2,
            "reserve_liters": 0.0,
        },
    )
    assert pool_res.status_code == 201, pool_res.text
    pool_id = pool_res.json()["id"]

    # Default receive (source="auto") for 3 canisters drains away (2) first, then empty (1)
    rec = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/receive",
        headers=operator_auth,
        json={
            "count": 3,
            "create_receipt": True,
            "gas_station_name": "АЗК WOG",
            "driver_name": "Водій Іван",
            "receipt_number": "CHK-AUTO-001",
            "comment": "Прийом 3 каністр",
        },
    )
    assert rec.status_code == 200, rec.text
    data = rec.json()
    assert data["away_refill_count"] == 0
    assert data["empty_count"] == 1
    assert data["full_count"] == 4
    assert data["total_count"] == 5
    assert data["available_liters"] == pytest.approx(80.0)

    # Stock balance auto-synced to 80L + automatic receipt created for 60L
    summary = (await client.get(f"/api/v1/fuel/summary?facility_id={fac_id}", headers=superadmin_auth)).json()
    assert summary["warehouse_balance_l"] == pytest.approx(80.0)

    receipts = (await client.get(f"/api/v1/fuel/receipts?facility_id={fac_id}", headers=superadmin_auth)).json()
    assert len(receipts) >= 1
    latest = receipts[0]
    assert latest["liters"] == pytest.approx(60.0)
    assert latest["receipt_number"] == "CHK-AUTO-001"

    # Requesting 2 more when only 1 free canister (empty=1, away=0) exists fails with 400
    over = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/receive",
        headers=operator_auth,
        json={
            "count": 2,
            "create_receipt": False,
            "driver_name": "Водій Іван",
            "receipt_number": "CHK-AUTO-002",
        },
    )
    assert over.status_code == 400


@pytest.mark.asyncio
async def test_system_adjustments_sync_fuel_stock_and_canister_pool(client, superadmin_auth):
    fac_id = (await client.get("/api/v1/facilities", headers=superadmin_auth)).json()[0]["id"]
    stock_id = (await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)).json()[0]["id"]

    pool_res = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "name": "Каністри Аудит",
            "canister_volume_l": 20.0,
            "full_count": 3,
            "empty_count": 1,
            "away_refill_count": 1,
            "reserve_liters": 0.0,
        },
    )
    assert pool_res.status_code == 201, pool_res.text
    pool_id = pool_res.json()["id"]

    # 1. Adjusting FuelStock.current_balance_l above pool capacity (5 * 20 = 100L) must be rejected
    too_big = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "FuelStock",
            "entity_id": stock_id,
            "facility_id": fac_id,
            "field_name": "current_balance_l",
            "new_value": "120.0",
            "reason": "Спроба перевищити місткість закріплених каністр",
        },
    )
    assert too_big.status_code == 400

    # 2. Valid FuelStock adjustment (45.0L) decomposes into 2 full (40L) + 5.0L reserve, keeping away=1
    adj_stock = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "FuelStock",
            "entity_id": stock_id,
            "facility_id": fac_id,
            "field_name": "current_balance_l",
            "new_value": "45.0",
            "reason": "Інвентаризація ГСМ: 2 повні каністри та 5 л в резерві",
        },
    )
    assert adj_stock.status_code == 201, adj_stock.text

    pools_after_stock = (await client.get(f"/api/v1/fuel/canisters?facility_id={fac_id}", headers=superadmin_auth)).json()
    assert pools_after_stock[0]["full_count"] == 2
    assert pools_after_stock[0]["reserve_liters"] == pytest.approx(5.0)
    assert pools_after_stock[0]["away_refill_count"] == 1
    assert pools_after_stock[0]["empty_count"] == 2
    assert pools_after_stock[0]["total_count"] == 5

    # 3. Direct CanisterPool field adjustments (full_count -> 3, reserve_liters -> 0) resync FuelStock
    adj_full = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "CanisterPool",
            "entity_id": pool_id,
            "facility_id": fac_id,
            "field_name": "full_count",
            "new_value": "3",
            "reason": "Фізичний перерахунок повних каністр на об'єкті",
        },
    )
    assert adj_full.status_code == 201, adj_full.text
    assert adj_full.json()["entity_type"] == "CanisterPool"

    adj_res = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "CanisterPool",
            "entity_id": pool_id,
            "facility_id": fac_id,
            "field_name": "reserve_liters",
            "new_value": "0",
            "reason": "Звірка нульового залишку в резервній ємності",
        },
    )
    assert adj_res.status_code == 201, adj_res.text

    pool_final = (await client.get(f"/api/v1/fuel/canisters?facility_id={fac_id}", headers=superadmin_auth)).json()[0]
    assert pool_final["full_count"] == 3
    assert pool_final["empty_count"] == 2
    assert pool_final["away_refill_count"] == 1
    assert pool_final["total_count"] == 6
    assert pool_final["reserve_liters"] == pytest.approx(0.0)
    assert pool_final["available_liters"] == pytest.approx(60.0)

    stock_final = (await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)).json()[0]
    assert stock_final["current_balance_l"] == pytest.approx(60.0)

    txs = (await client.get(f"/api/v1/fuel/canisters/transactions?pool_id={pool_id}", headers=superadmin_auth)).json()
    assert any(t["operation"] == "POOL_ADJUSTMENT" for t in txs)

    adjs = (await client.get(f"/api/v1/adjustments?facility_id={fac_id}", headers=superadmin_auth)).json()
    assert any(a["entity_type"] == "CanisterPool" and a["field_name"] == "full_count" for a in adjs)


