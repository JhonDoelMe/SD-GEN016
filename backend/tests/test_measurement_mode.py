import datetime
import io
import openpyxl
import pytest
from sqlalchemy import select

from backend.app.core.timezone import now_utc
from backend.app.models.audit import AuditLog
from backend.app.models.canister import CanisterPool, CanisterTransaction
from backend.app.models.fuel import FuelStock
from backend.app.models.generator import Generator
from backend.app.models.notification import NotificationLog
from backend.app.services.operational_guard_service import check_operational_guardrails


async def _setup_facility_and_pool(client, superadmin_auth):
    fac_res = await client.get("/api/v1/facilities", headers=superadmin_auth)
    assert fac_res.status_code == 200
    fac_id = fac_res.json()[0]["id"]

    # Wizard sets up generator #1 on facility 1
    gen_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "name": "Генератор Контрольного Заміру",
            "model": "KS-9000iE",
            "manufacturer": "Konner",
            "serial_number": "SN-MEAS-001",
            "rated_power_kw": 7.5,
            "tank_capacity_l": 40.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 100.0,
            "initial_fuel_tank_level_l": 30.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert gen_res.status_code == 200, gen_res.text
    gen_id = gen_res.json()["id"]

    stocks_res = await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)
    assert stocks_res.status_code == 200
    stock_id = stocks_res.json()[0]["id"]

    # Create canister pool: 8 x 20L full canisters = 160L
    pool_res = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "name": "Каністри 20л",
            "canister_volume_l": 20.0,
            "full_count": 8,
            "empty_count": 0,
            "away_refill_count": 0,
            "reserve_liters": 0.0,
        },
    )
    assert pool_res.status_code == 201, pool_res.text
    pool_id = pool_res.json()["id"]

    return fac_id, gen_id, stock_id, pool_id


@pytest.mark.asyncio
async def test_measurement_mode_rbac_start_overfill_bypass_guards_and_cancel(
    client, db_session, superadmin_auth, admin_auth, operator_auth, viewer_auth
):
    fac_id, gen_id, stock_id, pool_id = await _setup_facility_and_pool(client, superadmin_auth)

    # 1. Status endpoint is readable by any authenticated facility user
    for hdrs in (operator_auth, admin_auth, superadmin_auth, viewer_auth):
        st_res = await client.get(f"/api/v1/measurement/status?facility_id={fac_id}", headers=hdrs)
        assert st_res.status_code == 200, st_res.text
        assert st_res.json()["is_measuring"] is False
        assert st_res.json()["is_locked"] is False

    # 2. All mutating/admin measurement endpoints & history are strictly SuperAdmin-only
    for hdrs in (operator_auth, admin_auth, viewer_auth):
        assert (await client.get(f"/api/v1/measurement/history?facility_id={fac_id}", headers=hdrs)).status_code == 403
        assert (
            await client.post(
                "/api/v1/measurement/start",
                headers=hdrs,
                json={"facility_id": fac_id, "generator_id": gen_id},
            )
        ).status_code == 403

    # 3. Cannot start measurement when tank is not full (30.0L < 40.0L)
    not_full_res = await client.post(
        "/api/v1/measurement/start",
        headers=superadmin_auth,
        json={"facility_id": fac_id, "generator_id": gen_id},
    )
    assert not_full_res.status_code == 400
    assert "повн" in not_full_res.json()["detail"].lower()

    # Fill tank to 100% capacity (30 + 10 = 40.0L) -> stock becomes 150.0L
    tr_fill = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 10.0},
    )
    assert tr_fill.status_code == 201, tr_fill.text

    # 4. Cannot start measurement while generator is RUNNING
    start_gen = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "skip_cooldown": True},
    )
    assert start_gen.status_code == 200, start_gen.text

    while_running = await client.post(
        "/api/v1/measurement/start",
        headers=superadmin_auth,
        json={"facility_id": fac_id, "generator_id": gen_id},
    )
    assert while_running.status_code == 400
    assert "зупин" in while_running.json()["detail"].lower()

    stop_gen = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"generator_id": gen_id, "end_hours": 100.0},
    )
    assert stop_gen.status_code == 200, stop_gen.text

    # 5. SuperAdmin starts measurement mode cleanly (Full-to-Full: refills counter starts at 0.0)
    m_res = await client.post(
        "/api/v1/measurement/start",
        headers=superadmin_auth,
        json={"facility_id": fac_id, "generator_id": gen_id},
    )
    assert m_res.status_code == 200, m_res.text
    m = m_res.json()
    m_id = m["id"]
    assert m["status"] == "MEASURING"
    assert m["start_tank_level_l"] == pytest.approx(40.0)
    assert m["added_during_measurement_l"] == pytest.approx(0.0)
    assert m["measured_liters_total"] == pytest.approx(0.0)
    assert m["min_liters_threshold"] == pytest.approx(100.0)
    assert m["can_finish_full"] is False

    # Cannot start a duplicate measurement on the same facility
    dup_res = await client.post(
        "/api/v1/measurement/start",
        headers=superadmin_auth,
        json={"facility_id": fac_id, "generator_id": gen_id},
    )
    assert dup_res.status_code in (400, 409)

    # 6. During MEASURING: transfer bypassing book space (`tank_before=40L` yet operator pours 20L <= 40L cap) SUCCEEDS & clamps tank to 40L
    overfill_tr = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 20.0},
    )
    assert overfill_tr.status_code == 201, overfill_tr.text
    assert overfill_tr.json()["tank_balance_after"] == pytest.approx(40.0)

    # Exceeding physical tank capacity (>40L) in a single transfer still fails
    too_big_tr = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 45.0},
    )
    assert too_big_tr.status_code == 400

    st_after_tr = (await client.get(f"/api/v1/measurement/status?facility_id={fac_id}", headers=operator_auth)).json()
    assert st_after_tr["active"]["added_during_measurement_l"] == pytest.approx(20.0)
    assert st_after_tr["active"]["measured_liters_total"] == pytest.approx(20.0)

    # 7. Any manual fuel or consumption adjustments are FORBIDDEN during MEASURING (423 Locked)
    adj_tank = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "Generator",
            "entity_id": gen_id,
            "field_name": "fuel_tank_level_l",
            "new_value": "15.0",
            "reason": "Корекція під час заміру",
        },
    )
    assert adj_tank.status_code == 423

    adj_cons = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "Generator",
            "entity_id": gen_id,
            "field_name": "nominal_consumption_l_per_h",
            "new_value": "3.0",
            "reason": "Корекція витрати під час заміру",
        },
    )
    assert adj_cons.status_code == 423

    adj_stock = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "FuelStock",
            "entity_id": stock_id,
            "field_name": "current_balance_l",
            "new_value": "200.0",
            "reason": "Корекція складу під час заміру",
        },
    )
    assert adj_stock.status_code == 423

    adj_pool = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "CanisterPool",
            "entity_id": pool_id,
            "field_name": "full_count",
            "new_value": "1",
            "reason": "Корекція каністр під час заміру",
        },
    )
    assert adj_pool.status_code == 423

    upd_gen_cons = await client.put(
        f"/api/v1/generator/{gen_id}",
        headers=superadmin_auth,
        json={"nominal_consumption_l_per_h": 2.9},
    )
    assert upd_gen_cons.status_code == 423

    # 8. During MEASURING: empty tank warning is suppressed & over-burning clamps safely to 0.0
    run_start = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "skip_cooldown": True},
    )
    assert run_start.status_code == 200

    gen_row = await db_session.get(Generator, gen_id)
    gen_row.fuel_tank_level_l = 1.0
    await db_session.commit()
    await check_operational_guardrails(db_session)
    low_fuel_logs = (
        await db_session.execute(
            select(NotificationLog).where(NotificationLog.event_type == "LOW_FUEL")
        )
    ).scalars().all()
    assert len(low_fuel_logs) == 0

    run_stop = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"generator_id": gen_id, "end_hours": 125.0, "force_confirm": True},
    )
    assert run_stop.status_code == 200, run_stop.text

    gen_after_stop = (await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert gen_after_stop["fuel_tank_level_l"] == pytest.approx(0.0)

    # 9. Cannot finish-full before >= 100L refills poured (currently 20L)
    early_finish = await client.post(
        f"/api/v1/measurement/{m_id}/finish-full",
        headers=superadmin_auth,
        json={},
    )
    assert early_finish.status_code == 400
    assert "100" in early_finish.json()["detail"]

    # 10. Non-SuperAdmin cannot cancel; short reason fails; SuperAdmin cancel restores normal mode
    for hdrs in (operator_auth, admin_auth):
        assert (
            await client.post(
                f"/api/v1/measurement/{m_id}/cancel",
                headers=hdrs,
                json={"reason": "Несанкціоноване скасування"},
            )
        ).status_code == 403

    short_cancel = await client.post(
        f"/api/v1/measurement/{m_id}/cancel",
        headers=superadmin_auth,
        json={"reason": "ні"},
    )
    assert short_cancel.status_code == 422

    ok_cancel = await client.post(
        f"/api/v1/measurement/{m_id}/cancel",
        headers=superadmin_auth,
        json={"reason": "Хибний старт тестування"},
    )
    assert ok_cancel.status_code == 200, ok_cancel.text
    assert ok_cancel.json()["status"] == "CANCELLED"

    # Adjustment works again after cancel
    adj_after_cancel = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "Generator",
            "entity_id": gen_id,
            "field_name": "fuel_tank_level_l",
            "new_value": "40.0",
            "reason": "Підготовка до нового вимірювання",
        },
    )
    assert adj_after_cancel.status_code in (200, 201)


@pytest.mark.asyncio
async def test_measurement_mode_full_to_full_unblocked_blackout_and_53l_auto_canister_inventory(
    client, db_session, superadmin_auth, admin_auth, operator_auth
):
    fac_id, gen_id, stock_id, pool_id = await _setup_facility_and_pool(client, superadmin_auth)

    # Create Facility #2 + Generator #2 to verify lock isolation
    fac2_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={"name": "Другий Ізольований Об'єкт", "address": "вул. Ізоляції 2"},
    )
    assert fac2_res.status_code == 201
    fac2_id = fac2_res.json()["id"]
    gen2_res = await client.post(
        "/api/v1/generator",
        headers=superadmin_auth,
        json={
            "facility_id": fac2_id,
            "name": "Генератор Об'єкта 2",
            "model": "Honda EU30i",
            "manufacturer": "Honda",
            "serial_number": "SN-ISO-02",
            "rated_power_kw": 3.0,
            "tank_capacity_l": 20.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 1.5,
            "initial_operating_hours": 10.0,
            "initial_fuel_tank_level_l": 15.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert gen2_res.status_code == 201
    gen2_id = gen2_res.json()["id"]

    # Fill tank on facility 1 to 100% (30 + 10 = 40.0L) -> warehouse now has 150.0L
    await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 10.0},
    )

    # 1. Start measurement (100.0 hours, tank=40.0L full, nominal 2.0 L/h)
    m_res = await client.post(
        "/api/v1/measurement/start",
        headers=superadmin_auth,
        json={"facility_id": fac_id, "generator_id": gen_id},
    )
    assert m_res.status_code == 200
    m_id = m_res.json()["id"]
    assert m_res.json()["measured_liters_total"] == pytest.approx(0.0)

    # 2. Simulate running + refills totaling EXACTLY 100.0L (36 + 34 + 30 = 100L; remaining warehouse = 50.0L)
    # Total hours = 40.0h (100.0 -> 140.0h) => true consumption = 100.0 / 40.0 = 2.5 L/h!
    now_dt = now_utc()
    mr1 = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": (now_dt - datetime.timedelta(hours=50)).isoformat(),
            "end_time": (now_dt - datetime.timedelta(hours=32)).isoformat(),
            "start_hours": 100.0,
            "end_hours": 118.0,
            "fuel_consumed_l": 36.0,
            "skip_cooldown": True,
        },
    )
    assert mr1.status_code == 201, mr1.text

    tr1 = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 36.0},
    )
    assert tr1.status_code == 201, tr1.text

    mr2 = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": (now_dt - datetime.timedelta(hours=30)).isoformat(),
            "end_time": (now_dt - datetime.timedelta(hours=12)).isoformat(),
            "start_hours": 118.0,
            "end_hours": 136.0,
            "fuel_consumed_l": 34.0,
            "skip_cooldown": True,
        },
    )
    assert mr2.status_code == 201, mr2.text

    tr2 = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 34.0},
    )
    assert tr2.status_code == 201, tr2.text

    # Before 3rd refill, counter is 70L (<100L)
    st_pre = (await client.get(f"/api/v1/measurement/status?facility_id={fac_id}", headers=operator_auth)).json()
    assert st_pre["active"]["measured_liters_total"] == pytest.approx(70.0)
    assert st_pre["active"]["can_finish_full"] is False

    # 3rd run + final top-off refill of 30.0L -> 100.0L total poured!
    mr3 = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": (now_dt - datetime.timedelta(hours=10)).isoformat(),
            "end_time": (now_dt - datetime.timedelta(hours=6)).isoformat(),
            "start_hours": 136.0,
            "end_hours": 140.0,
            "fuel_consumed_l": 30.0,
            "skip_cooldown": True,
        },
    )
    assert mr3.status_code == 201, mr3.text

    tr3 = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 30.0},
    )
    assert tr3.status_code == 201, tr3.text

    # Start and verify finish-full is blocked while running, then stop and finish-full
    run_live = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "skip_cooldown": True},
    )
    assert run_live.status_code == 200

    st_mid = (await client.get(f"/api/v1/measurement/status?facility_id={fac_id}", headers=operator_auth)).json()
    assert st_mid["is_measuring"] is True
    assert st_mid["is_locked"] is False
    mid_m = st_mid["active"]
    assert mid_m["added_during_measurement_l"] == pytest.approx(100.0)
    assert mid_m["measured_liters_total"] == pytest.approx(100.0)
    assert mid_m["can_finish_full"] is False
    assert mid_m["is_generator_running"] is True
    assert len(mid_m["transfers"]) == 3

    fin_running = await client.post(
        f"/api/v1/measurement/{m_id}/finish-full",
        headers=superadmin_auth,
        json={"end_operating_hours": 140.0},
    )
    assert fin_running.status_code == 400

    stop_live = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"generator_id": gen_id, "end_hours": 140.0, "force_confirm": True},
    )
    assert stop_live.status_code == 200, stop_live.text

    # Click "Бак повний"
    fin_res = await client.post(
        f"/api/v1/measurement/{m_id}/finish-full",
        headers=superadmin_auth,
        json={"end_operating_hours": 140.0},
    )
    assert fin_res.status_code == 200, fin_res.text
    fin_m = fin_res.json()
    assert fin_m["status"] == "PENDING_INVENTORY"
    assert fin_m["total_fuel_consumed_l"] == pytest.approx(100.0)
    assert fin_m["total_hours_elapsed"] == pytest.approx(40.0)
    assert fin_m["calculated_consumption_l_per_h"] == pytest.approx(2.5)

    # Tank was reset to 100% capacity (40.0L) and immediately ready!
    gen_at_finish = (await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert gen_at_finish["fuel_tank_level_l"] == pytest.approx(40.0)

    # 3. During PENDING_INVENTORY: warehouse/tank fuel ops & adjustments are LOCKED (423),
    # BUT generator start/stop MUST SUCCEED for blackout resilience!
    st_locked = (await client.get(f"/api/v1/measurement/status?facility_id={fac_id}", headers=operator_auth)).json()
    assert st_locked["is_measuring"] is False
    assert st_locked["is_locked"] is True

    assert (
        await client.post(
            "/api/v1/fuel/transfer",
            headers=operator_auth,
            json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 5.0},
        )
    ).status_code == 423
    assert (
        await client.post(
            "/api/v1/fuel/receipt",
            headers=operator_auth,
            json={
                "facility_id": fac_id,
                "stock_id": stock_id,
                "liters": 20.0,
                "price_per_liter": 55.0,
                "driver_name": "Водій Тест",
                "receipt_number": "CHK-423",
            },
        )
    ).status_code == 423
    assert (
        await client.post(
            f"/api/v1/fuel/canisters/{pool_id}/dispatch",
            headers=operator_auth,
            json={"count": 1},
        )
    ).status_code == 423
    assert (
        await client.post(
            "/api/v1/adjustments",
            headers=superadmin_auth,
            json={
                "entity_type": "Generator",
                "entity_id": gen_id,
                "field_name": "current_operating_hours",
                "new_value": "145.0",
                "reason": "Блокування під час інвентаризації",
            },
        )
    ).status_code == 423

    # Blackout hits during PDF signing! Operator starts & stops generator freely (consumes 2h * 2.0 = 4.0L -> tank 36.0L)
    blackout_start = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "skip_cooldown": True},
    )
    assert blackout_start.status_code == 200, blackout_start.text
    blackout_stop = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"generator_id": gen_id, "end_hours": 142.0},
    )
    assert blackout_stop.status_code == 200, blackout_stop.text

    gen_during_blackout = (await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert gen_during_blackout["fuel_tank_level_l"] == pytest.approx(36.0)

    # Facility 2 must work completely unaffected
    st_fac2 = (await client.get(f"/api/v1/measurement/status?facility_id={fac2_id}", headers=superadmin_auth)).json()
    assert st_fac2["is_locked"] is False
    start_fac2 = await client.post(
        "/api/v1/generator/start",
        headers=superadmin_auth,
        json={"generator_id": gen2_id, "skip_cooldown": True},
    )
    assert start_fac2.status_code == 200, start_fac2.text

    # 4. Simplified Commission inventory: <3 members fails (422), >pool_capacity fails (400),
    # valid 53.0L stock automatically computes 2 full canisters (20L) + 13.0L reserve!
    two_members_payload = {
        "tank_full_confirmed": True,
        "stocks": [{"stock_id": stock_id, "fact_balance_l": 53.0}],
        "commission_members": [
            {"name": "Іваненко І.І.", "role": "Голова комісії"},
            {"name": "Петренко П.П.", "role": "Член комісії"},
        ],
    }
    assert (
        await client.post(f"/api/v1/measurement/{m_id}/inventory", headers=superadmin_auth, json=two_members_payload)
    ).status_code == 422

    over_cap_payload = {
        "tank_full_confirmed": True,
        "stocks": [{"stock_id": stock_id, "fact_balance_l": 200.0}],
        "commission_members": [
            {"name": "Іваненко І.І.", "role": "Голова комісії"},
            {"name": "Петренко П.П.", "role": "Головний інженер"},
            {"name": "Сидоренко С.С.", "role": "Оператор ГСМ"},
        ],
    }
    assert (
        await client.post(f"/api/v1/measurement/{m_id}/inventory", headers=superadmin_auth, json=over_cap_payload)
    ).status_code == 400

    valid_inv_payload = {
        "tank_full_confirmed": True,
        "stocks": [{"stock_id": stock_id, "fact_balance_l": 53.0}],
        "commission_members": [
            {"name": "Іваненко Іван Іванович", "role": "Голова комісії"},
            {"name": "Петренко Петро Петрович", "role": "Інженер з енергетики"},
            {"name": "Сидоренко Сергій Сергійович", "role": "Відповідальний оператор"},
        ],
        "notes": "Бак повний, на складі фактично 53 л",
    }
    inv_res = await client.post(
        f"/api/v1/measurement/{m_id}/inventory",
        headers=superadmin_auth,
        json=valid_inv_payload,
    )
    assert inv_res.status_code == 200, inv_res.text
    inv_m = inv_res.json()
    assert inv_m["status"] == "PENDING_APPROVAL"
    assert inv_m["statement_number"].startswith("ІНВ-")
    assert inv_m["can_approve"] is False
    # Verify auto-decomposition of 53.0L into 2 full x 20L + 13.0L reserve + 6 empty!
    auto_pool = inv_m["inventory_fact"]["pools"][0]
    assert auto_pool["fact_full"] == 2
    assert auto_pool["fact_empty"] == 6
    assert auto_pool["fact_away"] == 0
    assert auto_pool["fact_reserve_l"] == pytest.approx(13.0)

    # 5. Approve blocked until PDF statement is downloaded
    pre_approve = await client.post(f"/api/v1/measurement/{m_id}/approve", headers=superadmin_auth)
    assert pre_approve.status_code == 400
    assert "pdf" in pre_approve.json()["detail"].lower()

    assert (await client.get(f"/api/v1/measurement/{m_id}/statement-pdf", headers=admin_auth)).status_code == 403
    assert (await client.post(f"/api/v1/measurement/{m_id}/approve", headers=admin_auth)).status_code == 403

    # 6. Download A4 Landscape PDF statement
    pdf_res = await client.get(f"/api/v1/measurement/{m_id}/statement-pdf", headers=superadmin_auth)
    assert pdf_res.status_code == 200, pdf_res.text
    assert pdf_res.headers.get("content-type", "").startswith("application/pdf")
    assert pdf_res.content[:4] == b"%PDF"
    assert len(pdf_res.content) > 1500

    st_ready = (await client.get(f"/api/v1/measurement/status?facility_id={fac_id}", headers=superadmin_auth)).json()
    assert st_ready["active"]["can_approve"] is True

    # 7. SuperAdmin approves -> updates consumption, applies 53L (2 full + 13L reserve), preserves post-finish tank depletion (36.0L)
    app_res = await client.post(f"/api/v1/measurement/{m_id}/approve", headers=superadmin_auth)
    assert app_res.status_code == 200, app_res.text
    assert app_res.json()["status"] == "APPROVED"

    st_unlocked = (await client.get(f"/api/v1/measurement/status?facility_id={fac_id}", headers=operator_auth)).json()
    assert st_unlocked["is_locked"] is False
    assert st_unlocked["is_measuring"] is False
    assert st_unlocked["active"] is None

    gen_final = (await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert gen_final["nominal_consumption_l_per_h"] == pytest.approx(2.5)
    # Must NOT erase the 4.0L consumed by emergency blackout run while PDF was awaiting approval!
    assert gen_final["fuel_tank_level_l"] == pytest.approx(36.0)

    pool_row = await db_session.get(CanisterPool, pool_id)
    assert pool_row.full_count == 2
    assert pool_row.empty_count == 6
    assert pool_row.away_refill_count == 0
    assert float(pool_row.reserve_liters) == pytest.approx(13.0)

    stock_row = await db_session.get(FuelStock, stock_id)
    assert float(stock_row.current_balance_l) == pytest.approx(53.0)

    corr_txs = (
        await db_session.execute(
            select(CanisterTransaction).where(
                CanisterTransaction.pool_id == pool_id,
                CanisterTransaction.operation == "INVENTORY_CORRECTION",
            )
        )
    ).scalars().all()
    assert len(corr_txs) == 1

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "FuelMeasurement",
                AuditLog.entity_id == str(m_id),
            )
        )
    ).scalars().all()
    actions = {a.action for a in audit_rows}
    assert {
        "MEASUREMENT_STARTED",
        "MEASUREMENT_TANK_FULL",
        "MEASUREMENT_INVENTORY_SUBMITTED",
        "MEASUREMENT_STATEMENT_DOWNLOADED",
        "MEASUREMENT_APPROVED",
    }.issubset(actions)

    # Post-approval fuel transfer works again!
    tr_post = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"facility_id": fac_id, "stock_id": stock_id, "generator_id": gen_id, "liters": 4.0},
    )
    assert tr_post.status_code == 201, tr_post.text

    # Reports summary & Excel workbook include measurements sheet
    rep_res = await client.get(f"/api/v1/reports/summary?facility_id={fac_id}", headers=superadmin_auth)
    assert rep_res.status_code == 200, rep_res.text
    rep_data = rep_res.json()
    assert len(rep_data["measurements"]) == 1
    assert rep_data["measurements"][0]["statement_number"] == inv_m["statement_number"]
    assert rep_data["measurements"][0]["new_consumption_l_per_h"] == pytest.approx(2.5)

    xlsx_res = await client.get(f"/api/v1/reports/export-excel?facility_id={fac_id}", headers=superadmin_auth)
    assert xlsx_res.status_code == 200, xlsx_res.text
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_res.content))
    assert "Заміри та інвентаризація" in wb.sheetnames
    ws = wb["Заміри та інвентаризація"]
    rows_txt = " ".join(str(cell) for row in ws.iter_rows(values_only=True) for cell in row if cell is not None)
    assert inv_m["statement_number"] in rows_txt
