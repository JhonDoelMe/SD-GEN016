import pytest
import zipfile
import json
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import select

from backend.app.models.generator import Generator, GeneratorRun
from backend.app.models.facility import Facility
from backend.app.models.audit import AuditLog
from backend.app.services.generator_service import stop_generator
from backend.app.services.backup_service import create_backup, restore_backup, get_backup_dir, compute_sha256


@pytest.mark.asyncio
async def test_healthcheck_liveness_and_readiness(client):
    """MAIN-07: Test liveness and readiness healthchecks."""
    # 1. Liveness endpoint
    res_live = await client.get("/api/health/liveness")
    assert res_live.status_code == 200
    assert res_live.json() == {"status": "alive"}

    # 2. Readiness endpoint
    res_ready = await client.get("/api/health/readiness")
    assert res_ready.status_code == 200
    data = res_ready.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_healthcheck_database_failure(client):
    """MAIN-07: Test healthcheck returns 503 when database is unreachable."""
    class BrokenEngine:
        def connect(self):
            raise Exception("Database connection lost")

    with patch("backend.app.main.engine", BrokenEngine()):
        res = await client.get("/api/health")
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "disconnected"


@pytest.mark.asyncio
async def test_backup_creates_sha256_file(db_session):
    """BAK-04, BAK-05: Test backup is created with sha256 checksum file."""
    manifest = await create_backup(
        session=db_session,
        backup_type="partial",
        creator="test_agent",
        notes="Test sha256 creation"
    )
    backup_dir = get_backup_dir()
    zip_path = backup_dir / manifest["filename"]
    sha_path = zip_path.with_suffix(".sha256")

    assert zip_path.exists()
    assert sha_path.exists()

    expected_sha = compute_sha256(zip_path)
    assert expected_sha == manifest["sha256"]
    assert expected_sha in sha_path.read_text(encoding="utf-8")

    # Clean up test files
    zip_path.unlink(missing_ok=True)
    sha_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_restore_rejects_incomplete_backup_without_data_loss(db_session):
    """BAK-01: Incomplete backup archive is rejected before database is touched."""
    # Count facilities before test
    count_before = len((await db_session.execute(select(Facility))).scalars().all())
    assert count_before > 0

    backup_dir = get_backup_dir()
    bad_zip_path = backup_dir / "backup_incomplete_test.zip"

    # Create crafted incomplete archive missing required tables
    with zipfile.ZipFile(bad_zip_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"backup_id": "bad", "created_at": "2026-11-02T12:00:00"}))
        zf.writestr("database_export.json", json.dumps({"permissions": []}))

    with pytest.raises(ValueError) as excinfo:
        await restore_backup(
            session=db_session,
            zip_path=bad_zip_path,
            creator="test_suite"
        )
    assert "Неповна резервна копія" in str(excinfo.value)

    # Ensure existing database was not wiped
    count_after = len((await db_session.execute(select(Facility))).scalars().all())
    assert count_after == count_before

    # Clean up
    bad_zip_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_generator_stop_fuel_shortage_tracking_and_system_actor(client, superadmin_auth, db_session):
    """OPG-02, OPG-07: Fuel discrepancy recorded and system actor logged."""
    # Create generator with 5L fuel
    gen_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Тест Дефіциту",
            "model": "TG-DEF",
            "manufacturer": "PG",
            "serial_number": "SN-DEF-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 10.0,
            "initial_operating_hours": 10.0,
            "initial_fuel_tank_level_l": 5.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )
    assert gen_res.status_code == 200
    gen_id = gen_res.json()["id"]

    # Start generator
    await client.post("/api/v1/generator/start", headers=superadmin_auth, json={"generator_id": gen_id})

    # Trigger stop via system guard
    stopped_run = await stop_generator(
        db=db_session,
        generator_id=gen_id,
        user_id=None,
        reason="MAX_CONTINUOUS_RUN_EXCEEDED",
        system_note="Test automatic stop",
        actor_type="SYSTEM_GUARD"
    )
    assert stopped_run is not None
    assert stopped_run.status == "COMPLETED"

    # Verify audit log recorded system actor
    audit_q = (
        select(AuditLog)
        .where(AuditLog.entity_id == str(gen_id))
        .order_by(AuditLog.id.desc())
    )
    audit = (await db_session.execute(audit_q)).scalars().first()
    assert audit is not None
    assert audit.action == "GENERATOR_SAFETY_STOP"
    assert audit.user_id is None
    assert "SYSTEM_GUARD" in audit.details_json


@pytest.mark.asyncio
async def test_uploads_unauthorized_access(client):
    """INF-07: Unauthenticated request to /uploads/ must be rejected with 401."""
    res = await client.get("/uploads/test_secret_document.pdf")
    assert res.status_code == 401
