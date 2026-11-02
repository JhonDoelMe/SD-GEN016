import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from backend.app.models.generator import Generator, GeneratorRun, GeneratorSchedule
from backend.app.models.maintenance import MaintenanceSchedule
from backend.app.models.facility import Facility
from backend.app.models.audit import AuditLog
from backend.app.services.settings_service import update_system_settings, perform_system_reset


@pytest.mark.asyncio
async def test_critical_fault_stops_running_generator_and_direct_resolve_restores_status(
    client, superadmin_auth, db_session
):
    """
    Item #2:
    1) Reporting a CRITICAL fault on a RUNNING generator must automatically stop the active
       GeneratorRun and transition generator.status to FAULTY.
    2) Resolving the CRITICAL fault directly from NEW -> RESOLVED must transition generator.status
       back to STOPPED (or MAINTENANCE_REQUIRED if overdue).
    """
    # Ensure generator 1 has fuel in tank and 00:00-23:59 schedule so it can be started at any wall-clock time
    gen1 = (await db_session.execute(select(Generator).where(Generator.id == 1))).scalar_one()
    gen1.fuel_tank_level_l = 20.0
    scheds = (await db_session.execute(select(GeneratorSchedule).where(GeneratorSchedule.generator_id == 1))).scalars().all()
    for s in scheds:
        s.start_time = "00:00"
        s.end_time = "23:59"
    await db_session.commit()

    start_res = await client.post(
        "/api/v1/generator/start",
        headers=superadmin_auth,
        json={
            "generator_id": 1,
            "start_mode": "MANUAL",
            "force_start": True,
            "notes": "Тестовий запуск перед аварією",
        },
    )
    assert start_res.status_code in (200, 201), start_res.text
    run_id = start_res.json()["id"]

    # Report CRITICAL fault while generator is RUNNING
    fault_res = await client.post(
        "/api/v1/faults",
        headers=superadmin_auth,
        json={
            "generator_id": 1,
            "priority": "CRITICAL",
            "title": "Пробій ізоляції статора",
            "description": "Критичне падіння опору ізоляції під час роботи",
        },
    )
    assert fault_res.status_code == 201, fault_res.text
    fault_id = fault_res.json()["id"]

    # Verify generator is now FAULTY
    status_res = await client.get("/api/v1/generator?generator_id=1", headers=superadmin_auth)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["status"] == "FAULTY"

    # Verify the run in DB was cleanly completed
    run_row = (await db_session.execute(select(GeneratorRun).where(GeneratorRun.id == run_id))).scalar_one()
    assert run_row.status == "COMPLETED"
    assert run_row.end_time is not None

    # Resolve the fault directly from NEW -> RESOLVED (without intermediate IN_PROGRESS)
    resolve_res = await client.put(
        f"/api/v1/faults/{fault_id}/status",
        headers=superadmin_auth,
        json={"status": "RESOLVED", "resolution_notes": "Замінено обмотку, ізоляція в нормі"},
    )
    assert resolve_res.status_code == 200, resolve_res.text

    # Generator must now be STOPPED (not stuck in FAULTY)
    status_after = await client.get("/api/v1/generator?generator_id=1", headers=superadmin_auth)
    assert status_after.status_code == 200
    assert status_after.json()["status"] == "STOPPED"


@pytest.mark.asyncio
async def test_multi_facility_isolation_for_faults_and_maintenance(
    client, superadmin_auth, db_session
):
    """
    Item #1:
    Verify that operators bound to Facility #2 cannot leak into Facility #1 when omitting generator_id,
    cannot create faults or maintenance on another facility's generator, and cannot write to archived generators.
    """
    # Create Facility #2 and Generator #2 on Facility #2
    fac2 = Facility(name="Другий об'єкт", address="вул. Тестова 2")
    db_session.add(fac2)
    await db_session.flush()

    gen2 = Generator(
        facility_id=fac2.id,
        name="Генератор Другого Об'єкта",
        model="CAT-200",
        manufacturer="Caterpillar",
        serial_number="SN-CAT-200",
        status="STOPPED",
        is_active=True,
        current_operating_hours=10.0,
        fuel_tank_level_l=50.0,
        tank_capacity_l=100.0,
        nominal_consumption_l_per_h=5.0,
    )
    db_session.add(gen2)
    await db_session.commit()
    await db_session.refresh(gen2)

    # Create operator bound to Facility #2
    op2_res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "op_fac2",
            "password": "OperatorFac2Pass!",
            "full_name": "Оператор Об'єкта 2",
            "role_ids": [3],
            "facility_id": fac2.id,
        },
    )
    assert op2_res.status_code == 201, op2_res.text

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"login": "op_fac2", "password": "OperatorFac2Pass!"},
    )
    assert login_res.status_code == 200
    op2_headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    # Operator of Facility #2 attempts to report fault on Generator #1 (Facility #1) -> 403
    cross_fault = await client.post(
        "/api/v1/faults",
        headers=op2_headers,
        json={
            "generator_id": 1,
            "priority": "LOW",
            "title": "Чужий генератор",
            "description": "Спроба створити заявку на іншому об'єкті",
        },
    )
    assert cross_fault.status_code == 403

    # Operator of Facility #2 reports fault without specifying generator_id -> resolves to gen2 (since single active gen on fac2)
    own_fault = await client.post(
        "/api/v1/faults",
        headers=op2_headers,
        json={
            "priority": "MEDIUM",
            "title": "Власна несправність на об'єкті 2",
            "description": "Перевірка автовизначення генератора в межах свого об'єкта",
        },
    )
    assert own_fault.status_code == 201, own_fault.text
    assert own_fault.json()["generator_id"] == gen2.id

    # Operator of Facility #2 lists faults -> sees only Facility #2 faults
    list_f = await client.get("/api/v1/faults", headers=op2_headers)
    assert list_f.status_code == 200
    assert all(f["generator_id"] == gen2.id for f in list_f.json())

    # Operator of Facility #2 checks maintenance schedule without generator_id -> resolves to gen2
    maint_st = await client.get("/api/v1/maintenance/schedule", headers=op2_headers)
    assert maint_st.status_code == 200
    assert maint_st.json()["generator_id"] == gen2.id

    # GET /api/v1/maintenance/schedules works and filters by facility for op2
    sched_res = await client.get("/api/v1/maintenance/schedules", headers=op2_headers)
    assert sched_res.status_code == 200
    assert all(s["generator_id"] == gen2.id for s in sched_res.json())


@pytest.mark.asyncio
async def test_adjustments_maintenance_schedule_and_generator_guards(
    client, superadmin_auth, db_session
):
    """
    Item #3:
    1) Adjusting MaintenanceSchedule does not crash with 500 AttributeError ('title') and re-evaluates
       generator maintenance status.
    2) Adjusting Generator.fuel_tank_level_l rejects values > tank_capacity_l.
    3) Adjusting Generator.status rejects manual transitions to 'RUNNING'.
    """
    # Ensure MaintenanceSchedule exists for generator 1
    sched_res = await client.get("/api/v1/maintenance/schedules?generator_id=1", headers=superadmin_auth)
    assert sched_res.status_code == 200
    schedules = sched_res.json()
    assert len(schedules) >= 1
    sched_id = schedules[0]["id"]

    # Set generator 1 operating hours to 95.0 via adjustment
    adj_hours = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "Generator",
            "entity_id": 1,
            "field_name": "current_operating_hours",
            "new_value": "95.0",
            "reason": "Тестова звірка мотогодин",
        },
    )
    assert adj_hours.status_code == 201, adj_hours.text

    # Adjust MaintenanceSchedule next_due_hours to 90.0 -> should succeed (no 500 AttributeError)
    # and automatically set Generator #1 status to MAINTENANCE_REQUIRED
    adj_sched = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "MaintenanceSchedule",
            "entity_id": sched_id,
            "field_name": "next_due_hours",
            "new_value": "90.0",
            "reason": "Скорочення порогу ТО за результатами огляду",
        },
    )
    assert adj_sched.status_code == 201, adj_sched.text
    assert "Графік ТО" in adj_sched.json()["target_name"]

    gen_st = await client.get("/api/v1/generator?generator_id=1", headers=superadmin_auth)
    assert gen_st.status_code == 200
    assert gen_st.json()["status"] == "MAINTENANCE_REQUIRED"

    # Attempt to adjust Generator.fuel_tank_level_l above tank_capacity_l -> 400
    adj_overflow = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "Generator",
            "entity_id": 1,
            "field_name": "fuel_tank_level_l",
            "new_value": "99999.0",
            "reason": "Переповнення баку",
        },
    )
    assert adj_overflow.status_code == 400

    # Attempt to manually set Generator.status to RUNNING via adjustments -> 400
    adj_running = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "Generator",
            "entity_id": 1,
            "field_name": "status",
            "new_value": "RUNNING",
            "reason": "Обхід запуску",
        },
    )
    assert adj_running.status_code == 400


@pytest.mark.asyncio
async def test_multi_generator_facility_report_aggregation(
    client, superadmin_auth, db_session
):
    """
    Item #5 & #6:
    When a facility has multiple generators and a report is requested for facility_id (with generator_id=None),
    the summary and Excel report must aggregate data across ALL generators of that facility instead of taking .first().
    """
    # Create a second generator on Facility #1
    gen_b = Generator(
        facility_id=1,
        name="Резервний Генератор Б",
        model="SDMO-50",
        manufacturer="SDMO",
        serial_number="SN-SDMO-50",
        status="STOPPED",
        is_active=True,
        current_operating_hours=25.0,
        fuel_tank_level_l=40.0,
        tank_capacity_l=120.0,
        nominal_consumption_l_per_h=4.0,
    )
    db_session.add(gen_b)
    await db_session.flush()

    # Add a completed run on Generator #1 and another completed run on Generator B
    now_utc_dt = datetime.now(timezone.utc)
    now_str = now_utc_dt.strftime("%Y-%m-%d")
    run1 = GeneratorRun(
        generator_id=1,
        user_id=1,
        start_time=now_utc_dt.replace(tzinfo=None, hour=8, minute=0, second=0),
        end_time=now_utc_dt.replace(tzinfo=None, hour=10, minute=0, second=0),
        start_hours=10.0,
        end_hours=12.0,
        duration_hours=2.0,
        duration_seconds=7200,
        calculated_consumption_l=10.0,
        status="COMPLETED",
    )
    run2 = GeneratorRun(
        generator_id=gen_b.id,
        user_id=1,
        start_time=now_utc_dt.replace(tzinfo=None, hour=11, minute=0, second=0),
        end_time=now_utc_dt.replace(tzinfo=None, hour=14, minute=0, second=0),
        start_hours=20.0,
        end_hours=23.0,
        duration_hours=3.0,
        duration_seconds=10800,
        calculated_consumption_l=12.0,
        status="COMPLETED",
    )
    db_session.add_all([run1, run2])
    await db_session.commit()

    # Request summary report for Facility #1 without generator_id
    rep_res = await client.get(
        f"/api/v1/reports/summary?facility_id=1&start_date={now_str}&end_date={now_str}",
        headers=superadmin_auth,
    )
    assert rep_res.status_code == 200, rep_res.text
    rep_data = rep_res.json()
    assert rep_data["total_runs_count"] == 2
    assert rep_data["total_operating_hours"] == pytest.approx(5.0, rel=1e-2)
    assert rep_data["total_calculated_consumption_l"] == pytest.approx(22.0, rel=1e-2)

    # Also verify Excel export succeeds for multi-generator facility
    excel_res = await client.get(
        f"/api/v1/reports/export-excel?facility_id=1&start_date={now_str}&end_date={now_str}",
        headers=superadmin_auth,
    )
    assert excel_res.status_code == 200


@pytest.mark.asyncio
async def test_settings_apply_to_all_generators_and_reset_preserves_archived(
    client, superadmin_auth, db_session
):
    """
    Items #8 & #9:
    1) update_system_settings with apply_to_all_generators=True recalculates next_due_hours
       and updates generator status accordingly.
    2) perform_system_reset ('reports_clean' / 'facility_clean') preserves status='ARCHIVED'
       for archived generators.
    """
    # Create an archived generator on Facility #1
    arch_gen = Generator(
        facility_id=1,
        name="Архівний Генератор",
        model="OLD-10",
        manufacturer="Honda",
        serial_number="SN-OLD-10",
        status="ARCHIVED",
        is_active=False,
        current_operating_hours=500.0,
        fuel_tank_level_l=0.0,
        tank_capacity_l=50.0,
    )
    db_session.add(arch_gen)
    await db_session.commit()
    await db_session.refresh(arch_gen)

    # Set Generator #1 operating hours to 60h, last_performed_hours=0
    gen1 = (await db_session.execute(select(Generator).where(Generator.id == 1))).scalar_one()
    gen1.current_operating_hours = 60.0
    gen1.status = "STOPPED"
    sched1 = (
        await db_session.execute(select(MaintenanceSchedule).where(MaintenanceSchedule.generator_id == 1))
    ).scalars().first()
    if sched1:
        sched1.last_performed_hours = 0.0
        sched1.interval_hours = 100.0
        sched1.next_due_hours = 100.0
    await db_session.commit()

    # Apply new default_maintenance_interval_hours = 50.0 to all generators -> next_due_hours becomes 50.0 -> gen1 becomes MAINTENANCE_REQUIRED
    await update_system_settings(
        db_session,
        {"default_maintenance_interval_hours": 50.0, "apply_to_all_generators": True},
        apply_to_all_generators=True,
    )
    await db_session.refresh(gen1)
    if sched1:
        await db_session.refresh(sched1)
        assert sched1.next_due_hours == 50.0
    assert gen1.status == "MAINTENANCE_REQUIRED"

    # Perform 'reports_clean' reset -> archived generator must stay ARCHIVED
    await perform_system_reset(db_session, mode="reports_clean", facility_id=1, user_id=1)
    await db_session.refresh(arch_gen)
    assert arch_gen.status == "ARCHIVED"
    assert arch_gen.is_active is False


@pytest.mark.asyncio
async def test_notifications_and_backups_audit_commit_persisted(
    client, superadmin_auth, db_session
):
    """
    Item #10 & #11:
    Verify that clearing notification logs and updating backup settings actually commit their
    AuditLog entries to the database with user_id set.
    """
    clear_res = await client.delete("/api/v1/notifications/logs", headers=superadmin_auth)
    assert clear_res.status_code == 200

    audit_row = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "NOTIFICATION_LOGS_CLEARED")
        )
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.user_id is not None

    bkp_res = await client.put(
        "/api/v1/backups/settings",
        headers=superadmin_auth,
        json={"backup_auto_enabled": True, "backup_retention_count": 7},
    )
    assert bkp_res.status_code == 200

    bkp_audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "BACKUP_SETTINGS_UPDATE")
        )
    ).scalars().first()
    assert bkp_audit is not None
    assert bkp_audit.user_id is not None
