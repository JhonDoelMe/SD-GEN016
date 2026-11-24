import datetime
import pytest
from sqlalchemy import select

from backend.app.models.generator import Generator, GeneratorRun


@pytest.mark.asyncio
async def test_stop_generator_as_test_run_no_fuel_or_hours_or_report(client, superadmin_auth, db_session):
    """Тестовий пуск не змінює мотогодини, не списує паливо, прихований у журналі та виключений зі звітів."""
    gen_res = await client.get("/api/v1/generator", headers=superadmin_auth)
    assert gen_res.status_code == 200
    gen = gen_res.json()
    gen_id = gen["id"]
    assert gen.get("test_run_threshold_seconds", 120) == 120

    # Configure generator with 24/7 schedule, 100h, and 40L fuel
    wiz_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Тестовий генератор",
            "model": "Test-5000",
            "manufacturer": "Test",
            "serial_number": "SN-TEST-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 50.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 100.0,
            "initial_fuel_tank_level_l": 40.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert wiz_res.status_code == 200
    gen_id = wiz_res.json()["id"]

    # Start generator
    start_res = await client.post(
        "/api/v1/generator/start",
        headers=superadmin_auth,
        json={"generator_id": gen_id, "skip_cooldown": True},
    )
    assert start_res.status_code == 200

    # Stop as test run
    stop_res = await client.post(
        "/api/v1/generator/stop",
        headers=superadmin_auth,
        json={"generator_id": gen_id, "is_test": True, "note": "Перевірка зв'язку"},
    )
    assert stop_res.status_code == 200
    run_data = stop_res.json()
    assert run_data["status"] == "TEST"
    assert run_data["is_test"] is True
    assert run_data["calculated_consumption_l"] == 0.0
    assert run_data["end_hours"] == 100.0
    assert run_data["end_fuel_level_l"] == 40.0
    assert "[ТЕСТ]" in (run_data["note"] or "")

    # Verify generator hours & fuel untouched
    gen_after = (await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert gen_after["current_operating_hours"] == 100.0
    assert gen_after["fuel_tank_level_l"] == 40.0

    # Hidden from default /runs, visible with include_test=true
    runs_default = (await client.get(f"/api/v1/generator/runs?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert all(r["id"] != run_data["id"] for r in runs_default)

    runs_with_test = (
        await client.get(f"/api/v1/generator/runs?generator_id={gen_id}&include_test=true", headers=superadmin_auth)
    ).json()
    assert any(r["id"] == run_data["id"] and r["is_test"] is True for r in runs_with_test)

    # Excluded from report summary
    summary = (await client.get(f"/api/v1/reports/summary?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert summary["total_runs_count"] == 0
    assert summary["total_operating_hours"] == 0.0
    assert summary["total_calculated_consumption_l"] == 0.0


@pytest.mark.asyncio
async def test_admin_toggle_cleanup_and_delete_test_runs(client, superadmin_auth, db_session):
    """Адмін може позначати старі короткі пуски як тестові, повертати назад і видаляти тільки тестові."""
    gen = (await client.get("/api/v1/generator", headers=superadmin_auth)).json()
    gen_id = gen["id"]

    # Insert one short (30s) and one real (600s) COMPLETED run
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    short_run = GeneratorRun(
        generator_id=gen_id,
        user_id=1,
        start_time=now - datetime.timedelta(minutes=20),
        end_time=now - datetime.timedelta(minutes=20) + datetime.timedelta(seconds=30),
        start_hours=50.0,
        end_hours=50.008,
        duration_seconds=30,
        duration_hours=0.0083,
        start_fuel_level_l=30.0,
        end_fuel_level_l=29.98,
        calculated_consumption_l=0.02,
        status="COMPLETED",
        is_test=False,
    )
    real_run = GeneratorRun(
        generator_id=gen_id,
        user_id=1,
        start_time=now - datetime.timedelta(minutes=15),
        end_time=now - datetime.timedelta(minutes=5),
        start_hours=50.008,
        end_hours=50.175,
        duration_seconds=600,
        duration_hours=0.1667,
        start_fuel_level_l=29.98,
        end_fuel_level_l=29.6,
        calculated_consumption_l=0.38,
        status="COMPLETED",
        is_test=False,
    )
    db_session.add_all([short_run, real_run])
    await db_session.commit()
    await db_session.refresh(short_run)
    await db_session.refresh(real_run)

    # Cannot delete a real COMPLETED run
    del_real = await client.delete(f"/api/v1/generator/runs/{real_run.id}", headers=superadmin_auth)
    assert del_real.status_code == 400

    # Bulk mark short runs (< 120s) as test
    clean_res = await client.post(
        f"/api/v1/generator/runs/cleanup-short?generator_id={gen_id}&max_seconds=120&delete_runs=false",
        headers=superadmin_auth,
    )
    assert clean_res.status_code == 200
    assert clean_res.json()["marked_count"] == 1

    # Default runs list now shows only real_run
    runs_def = (await client.get(f"/api/v1/generator/runs?generator_id={gen_id}", headers=superadmin_auth)).json()
    ids_def = [r["id"] for r in runs_def]
    assert real_run.id in ids_def
    assert short_run.id not in ids_def

    # Toggle short_run back to COMPLETED and then back to TEST
    t1 = await client.post(
        f"/api/v1/generator/runs/{short_run.id}/toggle-test?is_test=false",
        headers=superadmin_auth,
    )
    assert t1.status_code == 200
    assert t1.json()["is_test"] is False
    assert t1.json()["status"] == "COMPLETED"

    t2 = await client.post(
        f"/api/v1/generator/runs/{short_run.id}/toggle-test?is_test=true",
        headers=superadmin_auth,
    )
    assert t2.status_code == 200
    assert t2.json()["is_test"] is True

    # Delete test run succeeds
    del_test = await client.delete(f"/api/v1/generator/runs/{short_run.id}", headers=superadmin_auth)
    assert del_test.status_code == 200
    assert del_test.json()["deleted_run_id"] == short_run.id
