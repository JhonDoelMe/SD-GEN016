import datetime
import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from backend.app.models.generator import Generator, GeneratorRun, GeneratorSchedule
from backend.app.models.maintenance import MaintenanceSchedule, MaintenanceRecord
from backend.app.models.fault import Fault
from backend.app.models.fuel import FuelTransfer
from backend.app.models.audit import AuditLog
from backend.app.core.timezone import now_utc


async def _create_test_generator(client, headers, **overrides):
    payload = {
        "facility_id": 1,
        "name": "Тестовий генератор SD-GEN016",
        "model": "K&S KSB 6500",
        "manufacturer": "K&S",
        "serial_number": f"SN-{datetime.datetime.now().timestamp()}",
        "rated_power_kw": 5.5,
        "tank_capacity_l": 25.0,
        "fuel_type": "А-95",
        "nominal_consumption_l_per_h": 2.0,
        "initial_operating_hours": 100.0,
        "initial_fuel_tank_level_l": 20.0,
        "work_schedule_start": "00:00",
        "work_schedule_end": "23:59",
        "maintenance_interval_hours": 300.0,
        "timezone": "Europe/Kyiv"
    }
    payload.update(overrides)
    res = await client.post("/api/v1/generator", headers=headers, json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# =====================================================================
# T-01, T-02, T-03, T-04: Start/Stop Concurrency, Double-click & DB Unique Index
# =====================================================================
@pytest.mark.asyncio
async def test_t01_t02_t03_t04_start_stop_idempotency_and_single_active_run(
    client, superadmin_auth, operator_auth, db_session
):
    gen = await _create_test_generator(client, superadmin_auth)
    gen_id = gen["id"]

    # T-01: Start with idempotency_key -> repeated request returns same run without duplicate
    idem_start_1 = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "fuel_level_l": 20.0, "idempotency_key": "START-KEY-001"}
    )
    assert idem_start_1.status_code == 200
    run_id = idem_start_1.json()["id"]

    idem_start_2 = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "fuel_level_l": 20.0, "idempotency_key": "START-KEY-001"}
    )
    assert idem_start_2.status_code == 200
    assert idem_start_2.json()["id"] == run_id

    # T-03: Repeated start of RUNNING generator without same idempotency_key -> Rejected (400)
    dup_start = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id}
    )
    assert dup_start.status_code == 400
    assert "працює" in dup_start.json()["detail"]

    # T-04: DB-level partial unique index prevents inserting a second RUNNING session directly in DB
    bad_second_run = GeneratorRun(
        generator_id=gen_id,
        user_id=1,
        start_time=now_utc(),
        start_hours=100.0,
        status="RUNNING"
    )
    db_session.add(bad_second_run)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    # Verify only 1 active run exists
    active_count = (await db_session.execute(
        select(func.count(GeneratorRun.id)).where(
            GeneratorRun.generator_id == gen_id,
            GeneratorRun.status == "RUNNING"
        )
    )).scalar()
    assert active_count == 1

    # T-02: Stop generator once -> succeeds; second concurrent/double-click stop -> Rejected (400), no double fuel deduction
    stop_1 = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"generator_id": gen_id, "end_hours": 102.0}
    )
    assert stop_1.status_code == 200
    assert stop_1.json()["status"] == "COMPLETED"
    assert stop_1.json()["calculated_consumption_l"] == 4.0  # 2h * 2.0 L/h

    stop_2 = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"generator_id": gen_id, "end_hours": 102.0}
    )
    assert stop_2.status_code == 400

    # Verify fuel was deducted only once (20.0 - 4.0 = 16.0 L)
    gen_after = (await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=operator_auth)).json()
    assert gen_after["fuel_tank_level_l"] == 16.0
    assert gen_after["current_operating_hours"] == 102.0


# =====================================================================
# T-05, T-06, T-07, T-08, T-09: Manual Runs, Overlaps & Counter Chronology
# =====================================================================
@pytest.mark.asyncio
async def test_t05_t06_t07_t08_t09_manual_runs_overlap_and_chronology(
    client, superadmin_auth, operator_auth
):
    gen = await _create_test_generator(
        client, superadmin_auth,
        initial_operating_hours=100.0,
        initial_fuel_tank_level_l=25.0,
        nominal_consumption_l_per_h=1.0
    )
    gen_id = gen["id"]

    base_dt = datetime.datetime(2026, 5, 10, 10, 0, 0, tzinfo=datetime.timezone.utc)
    t_10 = base_dt.isoformat()
    t_12 = (base_dt + datetime.timedelta(hours=2)).isoformat()
    t_11 = (base_dt + datetime.timedelta(hours=1)).isoformat()
    t_13 = (base_dt + datetime.timedelta(hours=3)).isoformat()
    t_14 = (base_dt + datetime.timedelta(hours=4)).isoformat()
    t_16 = (base_dt + datetime.timedelta(hours=6)).isoformat()

    # T-09: Negative operating hours delta (end_hours < start_hours) -> Rejected (400)
    neg_hours_res = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": t_10,
            "end_time": t_12,
            "start_hours": 100.0,
            "end_hours": 98.0
        }
    )
    assert neg_hours_res.status_code == 400
    assert "меншими за початкові" in neg_hours_res.json()["detail"]

    # Create valid first manual run [10:00, 12:00] with hours [100.0, 102.0]
    run1_res = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": t_10,
            "end_time": t_12,
            "start_hours": 100.0,
            "end_hours": 102.0,
            "idempotency_key": "MANUAL-KEY-001"
        }
    )
    assert run1_res.status_code == 201
    run1_id = run1_res.json()["id"]

    # T-05 (a): Idempotent retry with same idempotency_key returns existing record without double deduction
    run1_idem = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": t_10,
            "end_time": t_12,
            "start_hours": 100.0,
            "end_hours": 102.0,
            "idempotency_key": "MANUAL-KEY-001"
        }
    )
    assert run1_idem.status_code == 201
    assert run1_idem.json()["id"] == run1_id

    # T-05 (b): Duplicate manual run without idempotency_key -> Rejected (400)
    dup_manual = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": t_10,
            "end_time": t_12,
            "start_hours": 102.0,
            "end_hours": 104.0
        }
    )
    assert dup_manual.status_code == 400
    assert "Дублікат сеансу" in dup_manual.json()["detail"]

    # T-06: Manual run overlapping with existing completed run [11:00, 13:00] -> Rejected (400)
    overlap_res = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": t_11,
            "end_time": t_13,
            "start_hours": 102.0,
            "end_hours": 104.0
        }
    )
    assert overlap_res.status_code == 400
    assert "перетинається з існуючим історичним сеансом" in overlap_res.json()["detail"]

    # T-08: Out-of-sequence counter chronology (later interval [14:00, 16:00] with start_hours=101.0 < previous end_hours=102.0) -> Rejected (400)
    bad_chronology = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": t_14,
            "end_time": t_16,
            "start_hours": 101.0,
            "end_hours": 103.0
        }
    )
    assert bad_chronology.status_code == 400
    assert "Порушення хронології мотогодин" in bad_chronology.json()["detail"]

    # T-07: Manual run overlapping with an active RUNNING session -> Rejected (400)
    start_active = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id}
    )
    assert start_active.status_code == 200
    active_start_dt = datetime.datetime.fromisoformat(start_active.json()["start_time"]).replace(tzinfo=datetime.timezone.utc)

    overlap_active_res = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": (active_start_dt - datetime.timedelta(minutes=30)).isoformat(),
            "end_time": (active_start_dt + datetime.timedelta(minutes=10)).isoformat(),
            "start_hours": 102.0,
            "end_hours": 102.6,
            "force_confirm": True
        }
    )
    assert overlap_active_res.status_code == 400
    assert "активним сеансом" in overlap_active_res.json()["detail"]

    # Clean up active run
    await client.post("/api/v1/generator/stop", headers=operator_auth, json={"generator_id": gen_id})


# =====================================================================
# T-10, T-11, T-12, T-23: Fuel Safeguards, Rollback on Stop Error & Tank Capacity Validation
# =====================================================================
@pytest.mark.asyncio
async def test_t10_t11_t12_t23_fuel_bounds_rollback_and_tank_capacity(
    client, superadmin_auth, operator_auth
):
    gen = await _create_test_generator(
        client, superadmin_auth,
        tank_capacity_l=25.0,
        initial_fuel_tank_level_l=5.0,
        initial_operating_hours=50.0,
        nominal_consumption_l_per_h=3.0
    )
    gen_id = gen["id"]

    # T-10: Start with negative fuel_level_l -> Rejected (400)
    neg_start = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "fuel_level_l": -2.0}
    )
    assert neg_start.status_code == 400
    assert "від'ємним" in neg_start.json()["detail"]

    # T-11: Start with fuel_level_l > tank_capacity_l (30.0 > 25.0) -> Rejected (400)
    over_start = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "fuel_level_l": 30.0}
    )
    assert over_start.status_code == 400
    assert "перевищує місткість бака" in over_start.json()["detail"]

    # T-23: Reduce tank_capacity_l below current fuel_tank_level_l (3.0 < 5.0) -> Rejected (400)
    bad_cap_upd = await client.put(
        f"/api/v1/generator/{gen_id}",
        headers=superadmin_auth,
        json={"tank_capacity_l": 3.0}
    )
    assert bad_cap_upd.status_code == 400
    assert "меншою за поточний залишок" in bad_cap_upd.json()["detail"]

    # Start generator normally with 5.0 L
    start_ok = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id}
    )
    assert start_ok.status_code == 200

    # T-12: Stop with end_hours=53.0 (3h * 3.0 L/h = 9.0 L consumption > 5.0 L in tank) without actual end_fuel_level_l -> Rejected (400) & FULL ROLLBACK
    stop_fail = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"generator_id": gen_id, "end_hours": 53.0, "force_confirm": True}
    )
    assert stop_fail.status_code == 400
    assert "Недостатньо пального в баку" in stop_fail.json()["detail"]

    # Verify full rollback: generator is still RUNNING, operating hours still 50.0, fuel still 5.0 L
    gen_check = (await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=operator_auth)).json()
    assert gen_check["status"] == "RUNNING"
    assert gen_check["current_operating_hours"] == 50.0
    assert gen_check["fuel_tank_level_l"] == 5.0

    # Stop with end_fuel_level_l > tank_capacity_l (28.0 > 25.0) -> Rejected (400)
    stop_over = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"generator_id": gen_id, "end_hours": 51.0, "end_fuel_level_l": 28.0, "force_confirm": True}
    )
    assert stop_over.status_code == 400
    assert "перевищує місткість бака" in stop_over.json()["detail"]

    # Stop with valid actual end_fuel_level_l (e.g. operator measured 1.5 L remaining) -> Succeeds & audits reconciliation
    stop_reconciled = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "end_hours": 51.0,
            "end_fuel_level_l": 1.5,
            "fuel_discrepancy_reason": "Фактичний замір мірною лінійкою",
            "force_confirm": True
        }
    )
    assert stop_reconciled.status_code == 200
    assert stop_reconciled.json()["end_fuel_level_l"] == 1.5


# =====================================================================
# T-13, T-14, T-15, T-25: Generator Archiving, History Protection & Restore
# =====================================================================
@pytest.mark.asyncio
async def test_t13_t14_t15_t25_delete_archive_and_restore_generator(
    client, superadmin_auth, operator_auth, db_session
):
    # 1. Generator WITHOUT history -> Physical deletion allowed (T-15)
    empty_gen = await _create_test_generator(client, superadmin_auth, name="Генератор Без Історії")
    empty_id = empty_gen["id"]

    del_empty = await client.delete(f"/api/v1/generator/{empty_id}", headers=superadmin_auth)
    assert del_empty.status_code == 200
    assert del_empty.json()["deleted"] is True
    assert del_empty.json()["archived"] is False

    # Verify physically gone from DB
    in_db = await db_session.get(Generator, empty_id)
    assert in_db is None

    # 2. Generator WITH history -> Soft-archived, history 100% preserved (T-13, T-14, T-25)
    hist_gen = await _create_test_generator(client, superadmin_auth, name="Генератор З Історією")
    hist_id = hist_gen["id"]

    # Start -> T-13: Attempt delete while RUNNING -> Rejected (400)
    await client.post("/api/v1/generator/start", headers=operator_auth, json={"generator_id": hist_id})
    del_running = await client.delete(f"/api/v1/generator/{hist_id}", headers=superadmin_auth)
    assert del_running.status_code == 400
    assert "зараз працює" in del_running.json()["detail"]

    # Stop generator so it now has 1 completed GeneratorRun in history
    await client.post("/api/v1/generator/stop", headers=operator_auth, json={"generator_id": hist_id})

    # T-14: Delete stopped generator with history -> Soft-archived!
    del_hist = await client.delete(f"/api/v1/generator/{hist_id}", headers=superadmin_auth)
    assert del_hist.status_code == 200
    assert del_hist.json()["archived"] is True
    assert del_hist.json()["deleted"] is False

    # Verify generator record and its GeneratorRun history are preserved in DB!
    runs_after = (await client.get(f"/api/v1/generator/runs?generator_id={hist_id}", headers=superadmin_auth)).json()
    assert len(runs_after) == 1

    # Hidden from active list by default, visible with include_archived=true
    active_list = (await client.get("/api/v1/generator/list", headers=superadmin_auth)).json()
    assert not any(g["id"] == hist_id for g in active_list)
    all_list = (await client.get("/api/v1/generator/list?include_archived=true", headers=superadmin_auth)).json()
    archived_item = next(g for g in all_list if g["id"] == hist_id)
    assert archived_item["is_active"] is False
    assert archived_item["status"] == "ARCHIVED"

    # T-25: Archived generator cannot be started, updated, or have manual runs added
    start_arch = await client.post("/api/v1/generator/start", headers=operator_auth, json={"generator_id": hist_id})
    assert start_arch.status_code == 400
    assert "архівований" in start_arch.json()["detail"]

    upd_arch = await client.put(f"/api/v1/generator/{hist_id}", headers=superadmin_auth, json={"name": "Нова назва"})
    assert upd_arch.status_code == 400
    assert "архівований" in upd_arch.json()["detail"]

    # Restore archived generator -> returns to active STOPPED state
    restore_res = await client.post(f"/api/v1/generator/{hist_id}/restore", headers=superadmin_auth)
    assert restore_res.status_code == 200
    assert restore_res.json()["is_active"] is True
    assert restore_res.json()["status"] == "STOPPED"


# =====================================================================
# T-16, T-17, T-18: Maintenance Overdue Blocking & Force Override with Reason
# =====================================================================
@pytest.mark.asyncio
async def test_t16_t17_t18_maintenance_block_and_force_start_override(
    client, superadmin_auth, operator_auth, db_session
):
    gen = await _create_test_generator(
        client, superadmin_auth,
        initial_operating_hours=299.0,
        maintenance_interval_hours=300.0,
        initial_fuel_tank_level_l=20.0
    )
    gen_id = gen["id"]

    # Advance operating hours to 301.0 (overdue >= 300.0) via a 2-hour manual run
    now = datetime.datetime.now(datetime.timezone.utc)
    m_res = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": (now - datetime.timedelta(hours=3)).isoformat(),
            "end_time": (now - datetime.timedelta(hours=1)).isoformat(),
            "start_hours": 299.0,
            "end_hours": 301.0
        }
    )
    assert m_res.status_code == 201

    # Verify generator transitioned to MAINTENANCE_REQUIRED
    gen_state = (await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=operator_auth)).json()
    assert gen_state["status"] == "MAINTENANCE_REQUIRED"

    # T-16: Start with overdue maintenance without force_start_with_maintenance -> Blocked (400)
    start_blocked = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "force_start_with_maintenance": False}
    )
    assert start_blocked.status_code == 400
    assert "прострочено регламентне технічне обслуговування" in start_blocked.json()["detail"]

    # T-17: Force start by standard operator WITHOUT override permission -> Rejected (403)
    start_no_perm = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "force_start_with_maintenance": True,
            "force_start_reason": "Аварійне знеструмлення"
        }
    )
    assert start_no_perm.status_code == 403

    # Force start by SuperAdmin WITHOUT reason -> Rejected (400)
    start_no_reason = await client.post(
        "/api/v1/generator/start",
        headers=superadmin_auth,
        json={
            "generator_id": gen_id,
            "force_start_with_maintenance": True
        }
    )
    assert start_no_reason.status_code == 400
    assert "force_start_reason" in start_no_reason.json()["detail"]

    # T-18: Force start by SuperAdmin WITH valid reason -> Allowed & Audited!
    start_forced = await client.post(
        "/api/v1/generator/start",
        headers=superadmin_auth,
        json={
            "generator_id": gen_id,
            "force_start_with_maintenance": True,
            "force_start_reason": "Критичний блекаут серверної, ТО заплановано на вечір"
        }
    )
    assert start_forced.status_code == 200
    assert start_forced.json()["status"] == "RUNNING"

    # Verify GENERATOR_FORCE_START_MAINTENANCE in audit logs
    audit_res = (await client.get("/api/v1/audit?limit=10", headers=superadmin_auth)).json()
    assert any(a["action"] == "GENERATOR_FORCE_START_MAINTENANCE" for a in audit_res)

    # Stop generator
    await client.post("/api/v1/generator/stop", headers=superadmin_auth, json={"generator_id": gen_id})


# =====================================================================
# T-19, T-20: Timezone Normalization (Naive Local vs Aware UTC) & DST
# =====================================================================
@pytest.mark.asyncio
async def test_t19_t20_timezone_naive_and_aware_manual_run_normalization(
    client, superadmin_auth, operator_auth
):
    gen = await _create_test_generator(
        client, superadmin_auth,
        timezone="Europe/Kyiv",
        initial_operating_hours=10.0,
        initial_fuel_tank_level_l=20.0
    )
    gen_id = gen["id"]

    # T-19: Naive datetimes in summer (EEST = UTC+3): 2026-07-15 12:00:00 -> stored as 09:00:00 UTC
    res_naive = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": "2026-07-15T12:00:00",
            "end_time": "2026-07-15T14:00:00",
            "start_hours": 10.0,
            "end_hours": 12.0
        }
    )
    assert res_naive.status_code == 201
    r_naive = res_naive.json()
    assert r_naive["start_time"].startswith("2026-07-15T09:00:00")
    assert r_naive["end_time"].startswith("2026-07-15T11:00:00")
    assert r_naive["duration_seconds"] == 7200

    # T-20: Aware datetimes with explicit offset (+02:00 winter EET): 2026-01-15T12:00:00+02:00 -> stored as 10:00:00 UTC
    res_aware = await client.post(
        "/api/v1/generator/manual-run",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "start_time": "2026-01-15T12:00:00+02:00",
            "end_time": "2026-01-15T13:30:00+02:00",
            "start_hours": 8.5,
            "end_hours": 10.0
        }
    )
    assert res_aware.status_code == 201
    r_aware = res_aware.json()
    assert r_aware["start_time"].startswith("2026-01-15T10:00:00")
    assert r_aware["end_time"].startswith("2026-01-15T11:30:00")
    assert r_aware["duration_seconds"] == 5400


# =====================================================================
# T-21, T-22, T-24 & GEN-05/11: Controlled Facility Transfer, Wizard & Unconfigured Guard
# =====================================================================
@pytest.mark.asyncio
async def test_t21_t22_t24_facility_transfer_wizard_and_status_consistency(
    client, superadmin_auth, operator_auth, db_session
):
    # Create target facility
    fac_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={
            "name": "Філія Полтава (Тест Перенесення)",
            "address": "вул. Соборності, 10",
            "timezone": "Europe/Kyiv"
        }
    )
    assert fac_res.status_code == 201
    target_fac_id = fac_res.json()["id"]

    gen = await _create_test_generator(client, superadmin_auth, name="Генератор Трансфер")
    gen_id = gen["id"]

    # T-21 (a): Direct facility_id change via general PUT /generator/{id} -> Rejected (400)
    direct_change = await client.put(
        f"/api/v1/generator/{gen_id}",
        headers=superadmin_auth,
        json={"facility_id": target_fac_id}
    )
    assert direct_change.status_code == 400
    assert "Пряма зміна об'єкта" in direct_change.json()["detail"]

    # Start generator -> T-21 (b): Transfer RUNNING generator via transfer-facility -> Rejected (400)
    await client.post("/api/v1/generator/start", headers=operator_auth, json={"generator_id": gen_id})
    trans_running = await client.post(
        f"/api/v1/generator/{gen_id}/transfer-facility",
        headers=superadmin_auth,
        json={"target_facility_id": target_fac_id, "reason": "Переїзд під час роботи"}
    )
    assert trans_running.status_code == 400
    assert "активної роботи" in trans_running.json()["detail"]

    # Stop generator
    await client.post("/api/v1/generator/stop", headers=operator_auth, json={"generator_id": gen_id})

    # T-22: Controlled transfer of stopped generator -> Succeeds & logs GENERATOR_FACILITY_TRANSFERRED
    trans_ok = await client.post(
        f"/api/v1/generator/{gen_id}/transfer-facility",
        headers=superadmin_auth,
        json={"target_facility_id": target_fac_id, "reason": "Планова ротація резервного обладнання"}
    )
    assert trans_ok.status_code == 200
    assert trans_ok.json()["facility_id"] == target_fac_id

    # GEN-11: Unconfigured generator (is_configured=False) cannot be started!
    db_gen = await db_session.get(Generator, gen_id)
    db_gen.is_configured = False
    await db_session.commit()

    start_unconf = await client.post(
        "/api/v1/generator/start",
        headers=superadmin_auth,
        json={"generator_id": gen_id}
    )
    assert start_unconf.status_code == 400
    assert "не налаштовано" in start_unconf.json()["detail"]

    # GEN-05: Configure this specific generator via Wizard using generator_id
    wiz_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "generator_id": gen_id,
            "facility_id": target_fac_id,
            "name": "Генератор Трансфер Налаштований",
            "model": "K&S 6500 Pro",
            "manufacturer": "K&S",
            "serial_number": "SN-WIZ-TARGET",
            "rated_power_kw": 5.5,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 105.0,
            "initial_fuel_tank_level_l": 20.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )
    assert wiz_res.status_code == 200
    assert wiz_res.json()["id"] == gen_id
    assert wiz_res.json()["is_configured"] is True

    # T-24: Reconcile endpoint verifies and restores status consistency
    rec_res = await client.post(f"/api/v1/generator/{gen_id}/reconcile", headers=superadmin_auth)
    assert rec_res.status_code == 200
    assert rec_res.json()["status"] == "STOPPED"
