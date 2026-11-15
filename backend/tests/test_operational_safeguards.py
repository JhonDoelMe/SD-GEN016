import datetime
import pytest
from sqlalchemy import select

from backend.app.models.generator import Generator, GeneratorRun, GeneratorSchedule
from backend.app.models.notification import NotificationLog
from backend.app.services.operational_guard_service import check_operational_guardrails
from backend.app.core.timezone import now_utc, to_facility_time


@pytest.mark.asyncio
async def test_typo_guard_on_generator_stop(client, superadmin_auth, operator_auth):
    """
    Test that typo guard blocks impossible single-session moto-hours unless force_confirm is provided.
    """
    # 1. Wizard setup: generator with 100 initial hours
    await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Тест Запобіжника",
            "model": "TG-500",
            "manufacturer": "TestGen",
            "serial_number": "SN-TYPO-01",
            "rated_power_kw": 5.0,
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
    )

    # 2. Start generator
    start_res = await client.post("/api/v1/generator/start", headers=operator_auth, json={})
    assert start_res.status_code == 200

    # 3. Typo: operator enters 120.0 hours (delta = 20.0 > 14.0 max session limit) without force_confirm
    stop_typo = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"end_hours": 120.0, "force_confirm": False}
    )
    assert stop_typo.status_code == 400
    assert "Запобіжник опечатки" in stop_typo.json()["detail"]

    # 4. Same end_hours with force_confirm=True and actual end_fuel_level_l should succeed
    stop_ok = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"end_hours": 120.0, "end_fuel_level_l": 0.0, "force_confirm": True, "note": "Підтверджений тривалий сеанс"}
    )
    assert stop_ok.status_code == 200
    assert stop_ok.json()["status"] == "COMPLETED"
    assert stop_ok.json()["end_hours"] == 120.0


@pytest.mark.asyncio
async def test_fuel_receipt_scale_and_price_sanity_checks(client, superadmin_auth, operator_auth):
    """
    Test fuel receipt safeguards: volume > 1000L or abnormal price per liter are guarded.
    """
    # 1. Reject receipt with 2500 L (> 1000 L warning threshold) without force_confirm
    res_large = await client.post(
        "/api/v1/fuel/receipt",
        headers=operator_auth,
        json={
            "liters": 2500.0,
            "cost_total": 140000.0,
            "fuel_type": "А-95",
            "driver_name": "Іванов І.І.",
            "receipt_number": "ЧЕК-LARGE-01",
            "force_confirm": False
        }
    )
    assert res_large.status_code == 400
    assert "Запобіжник об'єму палива" in res_large.json()["detail"]

    # Operator without fuel:receipt:override is rejected with 403 (FUEL-05)
    res_large_forbidden = await client.post(
        "/api/v1/fuel/receipt",
        headers=operator_auth,
        json={
            "liters": 2500.0,
            "cost_total": 140000.0,
            "fuel_type": "А-95",
            "driver_name": "Іванов І.І.",
            "receipt_number": "ЧЕК-LARGE-01",
            "force_confirm": True
        }
    )
    assert res_large_forbidden.status_code == 403

    # 2. Allow large receipt with force_confirm=True (Admin/SuperAdmin)
    res_large_ok = await client.post(
        "/api/v1/fuel/receipt",
        headers=superadmin_auth,
        json={
            "liters": 2500.0,
            "cost_total": 140000.0,
            "fuel_type": "А-95",
            "driver_name": "Іванов І.І.",
            "receipt_number": "ЧЕК-LARGE-01",
            "force_confirm": True
        }
    )
    assert res_large_ok.status_code == 201
    assert res_large_ok.json()["liters"] == 2500.0

    # 3. Reject receipt with abnormal price: 100 L for 100 грн (1 грн/л < 15 грн/л) without force_confirm
    res_abnormal = await client.post(
        "/api/v1/fuel/receipt",
        headers=operator_auth,
        json={
            "liters": 100.0,
            "cost_total": 100.0,
            "fuel_type": "А-95",
            "driver_name": "Сидоров С.С.",
            "receipt_number": "ЧЕК-PRICE-01",
            "force_confirm": False
        }
    )
    assert res_abnormal.status_code == 400
    assert "Запобіжник вартості палива" in res_abnormal.json()["detail"]

    # Operator without override permission is rejected with 403
    res_abnormal_forbidden = await client.post(
        "/api/v1/fuel/receipt",
        headers=operator_auth,
        json={
            "liters": 100.0,
            "cost_total": 100.0,
            "fuel_type": "А-95",
            "driver_name": "Сидоров С.С.",
            "receipt_number": "ЧЕК-PRICE-01",
            "force_confirm": True
        }
    )
    assert res_abnormal_forbidden.status_code == 403

    # 4. Allow abnormal receipt with force_confirm=True (Admin/SuperAdmin)
    res_abnormal_ok = await client.post(
        "/api/v1/fuel/receipt",
        headers=superadmin_auth,
        json={
            "liters": 100.0,
            "cost_total": 100.0,
            "fuel_type": "А-95",
            "driver_name": "Сидоров С.С.",
            "receipt_number": "ЧЕК-PRICE-01",
            "force_confirm": True
        }
    )
    assert res_abnormal_ok.status_code == 201
    assert res_abnormal_ok.json()["price_per_liter"] == 1.0


@pytest.mark.asyncio
async def test_operational_guardrail_empty_tank_fuse(client, superadmin_auth, operator_auth, db_session):
    """
    Test that a generator running for > 12 hours is automatically stopped by the guardrail.
    """
    # 1. Ensure a running generator
    await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Захист Бака",
            "model": "TG-TANK",
            "manufacturer": "PG",
            "serial_number": "SN-TANK-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 50.0,
            "initial_fuel_tank_level_l": 25.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )

    start_res = await client.post("/api/v1/generator/start", headers=operator_auth, json={})
    assert start_res.status_code == 200

    # 2. Simulate 13 hours of runtime by modifying run.start_time
    q = select(GeneratorRun).where(GeneratorRun.status == "RUNNING").order_by(GeneratorRun.id.desc())
    res = await db_session.execute(q)
    run = res.scalars().first()
    assert run is not None

    thirteen_hours_ago = now_utc() - datetime.timedelta(hours=13)
    run.start_time = thirteen_hours_ago
    await db_session.commit()

    # 3. Trigger operational guardrails check
    guard_results = await check_operational_guardrails(db_session)
    assert guard_results["safety_stopped_max_run"] >= 1

    # 4. Verify run was completed and generator stopped
    await db_session.refresh(run)
    assert run.status == "COMPLETED"
    assert "захист від порожнього бака" in run.note

    gen_q = select(Generator).where(Generator.id == run.generator_id)
    gen_res = await db_session.execute(gen_q)
    gen = gen_res.scalars().first()
    assert gen.status == "STOPPED"


@pytest.mark.asyncio
async def test_operational_guardrail_schedule_end_auto_stop(client, superadmin_auth, operator_auth, db_session):
    """
    Test that a running generator is auto-stopped when working hours end.
    """
    # 1. Configure generator with a schedule that is already closed (e.g. 01:00 to 01:05)
    await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Розклад Графік",
            "model": "TG-SCHED",
            "manufacturer": "PG",
            "serial_number": "SN-SCHED-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 50.0,
            "initial_fuel_tank_level_l": 25.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )

    # Start generator during allowed window
    await client.post("/api/v1/generator/start", headers=operator_auth, json={})

    # Now change generator schedule to an expired window (e.g. 02:00 to 02:05) to simulate end of work day
    q_gen = select(Generator).order_by(Generator.id.desc())
    g_res = await db_session.execute(q_gen)
    gen = g_res.scalars().first()

    sched_q = select(GeneratorSchedule).where(GeneratorSchedule.generator_id == gen.id)
    s_res = await db_session.execute(sched_q)
    sched = s_res.scalars().first()
    from backend.app.core.timezone import to_facility_time
    cur_h = to_facility_time(now_utc()).hour
    sched.start_time = "12:00" if cur_h == 2 else "02:00"
    sched.end_time = "12:05" if cur_h == 2 else "02:05"
    await db_session.commit()

    # 2. Trigger guardrails check
    guard_results = await check_operational_guardrails(db_session)
    assert guard_results["auto_stopped_schedule"] >= 1

    # 3. Verify generator stopped with note about schedule
    q_run = select(GeneratorRun).where(GeneratorRun.generator_id == gen.id).order_by(GeneratorRun.id.desc())
    run_res = await db_session.execute(q_run)
    run = run_res.scalars().first()
    assert run.status == "COMPLETED"
    assert "Автоматична зупинка за розкладом" in run.note

    await db_session.refresh(gen)
    assert gen.status == "STOPPED"


@pytest.mark.asyncio
async def test_operational_guardrail_heartbeat_reminder(client, superadmin_auth, operator_auth, db_session):
    """
    Test that running generator >= 4 hours triggers a heartbeat reminder.
    """
    # 1. Wizard setup with 24/7 schedule
    await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Нагадування 4 Години",
            "model": "TG-HEARTBEAT",
            "manufacturer": "PG",
            "serial_number": "SN-HB-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 10.0,
            "initial_fuel_tank_level_l": 25.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )

    # Start generator
    await client.post("/api/v1/generator/start", headers=operator_auth, json={})

    # Set start_time to 5 hours ago
    q = select(GeneratorRun).where(GeneratorRun.status == "RUNNING").order_by(GeneratorRun.id.desc())
    res = await db_session.execute(q)
    run = res.scalars().first()
    assert run is not None
    run.start_time = now_utc() - datetime.timedelta(hours=5)
    await db_session.commit()

    # Trigger guardrails check
    guard_results = await check_operational_guardrails(db_session)
    assert guard_results["heartbeats_sent"] >= 1

    # Verify notification log
    log_q = select(NotificationLog).where(
        NotificationLog.event_type == "GENERATOR_HEARTBEAT",
        NotificationLog.generator_id == run.generator_id
    )
    log_res = await db_session.execute(log_q)
    hb_log = log_res.scalars().first()
    assert hb_log is not None
    assert "досі працює" in hb_log.title

    expected_local_start = to_facility_time(run.start_time, "Europe/Kyiv").strftime("%H:%M")
    utc_start = run.start_time.strftime("%H:%M")
    assert f"з {expected_local_start}" in hb_log.body
    assert f"з {utc_start}" not in hb_log.body
    assert "~15.0 л" in hb_log.body
    assert "~25.0 л" not in hb_log.body


@pytest.mark.asyncio
async def test_preventive_warmup_start_stop_and_idle_recommendation(client, superadmin_auth, operator_auth, db_session):
    """
    Test Preventive Warmup lifecycle: admin settings, idle detection, warmup start/stop note preservation.
    """
    # 1. Configure warmup settings via admin API
    put_res = await client.put(
        "/api/v1/system/settings",
        headers=superadmin_auth,
        json={
            "warmup_reminder_enabled": True,
            "warmup_idle_days": 7,
            "warmup_duration_minutes": 10,
        },
    )
    assert put_res.status_code == 200

    # 2. Setup configured generator created 10 days ago with no runs yet
    wiz_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Прогрів Тест",
            "model": "TG-WARMUP",
            "manufacturer": "PG",
            "serial_number": "SN-WU-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 50.0,
            "initial_fuel_tank_level_l": 20.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert wiz_res.status_code == 200
    gen_id = wiz_res.json()["id"]

    q_gen = select(Generator).where(Generator.id == gen_id)
    gen = (await db_session.execute(q_gen)).scalars().first()
    gen.created_at = now_utc() - datetime.timedelta(days=10)
    await db_session.commit()

    # 3. Verify generator endpoint flags warmup_recommended
    get_res = await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=operator_auth)
    assert get_res.status_code == 200
    gen_data = get_res.json()
    assert gen_data["days_since_last_run"] >= 10
    assert gen_data["warmup_recommended"] is True
    assert gen_data["warmup_duration_minutes"] == 10

    # 4. Start warmup run and confirm active note + stop note preservation
    start_res = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "is_warmup": True},
    )
    assert start_res.status_code == 200
    active_run = start_res.json()
    assert active_run["note"].startswith("Профілактичний прогрів")

    stop_res = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={
            "generator_id": gen_id,
            "end_hours": 50.2,
            "note": "Успішно прогріто 10 хв",
        },
    )
    assert stop_res.status_code == 200
    stopped_run = stop_res.json()
    assert stopped_run["note"] == "Профілактичний прогрів — Успішно прогріто 10 хв"

    # 5. After warmup run, idle days resets to 0 and warmup is no longer recommended
    after_res = await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=operator_auth)
    assert after_res.status_code == 200
    after_data = after_res.json()
    assert after_data["days_since_last_run"] == 0
    assert after_data["warmup_recommended"] is False


@pytest.mark.asyncio
async def test_preventive_warmup_guardrails_done_and_due_notifications(client, superadmin_auth, operator_auth, db_session):
    """
    Test guardrails send GENERATOR_WARMUP_DONE after warmup duration and GENERATOR_WARMUP_DUE after idle threshold without spamming.
    """
    await client.put(
        "/api/v1/system/settings",
        headers=superadmin_auth,
        json={
            "warmup_reminder_enabled": True,
            "warmup_idle_days": 5,
            "warmup_duration_minutes": 15,
        },
    )

    # Idle stopped generator (8 days old, no runs)
    wiz_due = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Простій Прогрів",
            "model": "TG-DUE",
            "manufacturer": "PG",
            "serial_number": "SN-WU-DUE",
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
    due_gen_id = wiz_due.json()["id"]
    due_gen = (await db_session.execute(select(Generator).where(Generator.id == due_gen_id))).scalars().first()
    due_gen.created_at = now_utc() - datetime.timedelta(days=8)
    await db_session.commit()

    # Active warmup generator started 20 minutes ago (created as distinct second generator)
    wiz_done = await client.post(
        "/api/v1/generator",
        headers=superadmin_auth,
        json={
            "name": "Генератор Завершення Прогріву",
            "model": "TG-DONE",
            "manufacturer": "PG",
            "serial_number": "SN-WU-DONE",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 15.0,
            "initial_fuel_tank_level_l": 20.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert wiz_done.status_code == 201
    done_gen_id = wiz_done.json()["id"]
    assert done_gen_id != due_gen_id
    await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": done_gen_id, "is_warmup": True},
    )
    done_run = (
        await db_session.execute(
            select(GeneratorRun).where(
                GeneratorRun.generator_id == done_gen_id,
                GeneratorRun.status == "RUNNING",
            )
        )
    ).scalars().first()
    done_run.start_time = now_utc() - datetime.timedelta(minutes=20)
    await db_session.commit()

    # First guardrails pass: both notifications should be sent once
    first_guard = await check_operational_guardrails(db_session)
    assert first_guard["warmup_due_sent"] >= 1
    assert first_guard["warmup_done_sent"] >= 1

    due_logs = (
        await db_session.execute(
            select(NotificationLog).where(
                NotificationLog.generator_id == due_gen_id,
                NotificationLog.event_type == "GENERATOR_WARMUP_DUE",
            )
        )
    ).scalars().all()
    assert len(due_logs) == 1

    done_logs = (
        await db_session.execute(
            select(NotificationLog).where(
                NotificationLog.generator_id == done_gen_id,
                NotificationLog.event_type == "GENERATOR_WARMUP_DONE",
            )
        )
    ).scalars().all()
    assert len(done_logs) == 1

    # Immediate second pass: cooldown/one-shot guard prevents duplicates
    second_guard = await check_operational_guardrails(db_session)
    assert second_guard["warmup_due_sent"] == 0
    assert second_guard["warmup_done_sent"] == 0
