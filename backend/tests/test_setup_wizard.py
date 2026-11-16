"""Tests for Stage 3 Web Setup Wizard (`/setup`, `/api/v1/setup/*`) and Zero-.env migration."""

import json
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.app.config import settings
from backend.app.core.bootstrap import (
    is_setup_required,
    load_instance_config,
    set_setup_required,
)
from backend.app.core.secrets import ENC_PREFIX
from backend.app.core.security import verify_password
from backend.app.database import AsyncSessionLocal, reinit_database_engine
from backend.app.main import app
from backend.app.models.settings import SystemSetting
from backend.app.models.user import User
from backend.app.services.settings_service import set_runtime_setting


@pytest.mark.asyncio
async def test_setup_endpoints_locked_when_system_already_initialized(client):
    set_setup_required(False)

    r_status = await client.get("/api/v1/setup/status")
    assert r_status.status_code == 200
    assert r_status.json()["setup_required"] is False

    r_page = await client.get("/setup", follow_redirects=False)
    assert r_page.status_code == 302
    assert r_page.headers["location"] == "/"

    r_test = await client.post("/api/v1/setup/test-db", json={"db_type": "sqlite"})
    assert r_test.status_code == 403

    r_complete = await client.post(
        "/api/v1/setup/complete",
        json={
            "db_type": "sqlite",
            "organization_name": "Evil",
            "admin_login": "hacker",
            "admin_email": "hacker@evil.com",
            "admin_full_name": "Evil Actor",
            "admin_password": "StrongPassword99!",
        },
    )
    assert r_complete.status_code == 403


@pytest.mark.asyncio
async def test_clean_install_setup_wizard_flow_and_permanent_lock(tmp_path, monkeypatch):
    cfg_path = tmp_path / "instance.config.json"
    monkeypatch.setenv("SDGEN_INSTANCE_CONFIG", str(cfg_path))
    # Ensure SQLite target inside isolated tmp_path or clean relative filename cleaned up cleanly
    orig_db_url = settings.DATABASE_URL
    orig_secret = settings.APP_SECRET_KEY
    wizard_db_name = f"wizard_test_{tmp_path.name}.db"
    wizard_db_file = f"./data/{wizard_db_name}"

    from pathlib import Path
    data_db_path = Path(wizard_db_file)

    try:
        set_setup_required(True)
        transport = ASGITransport(app=app)

        # Shared hosting / custom host must be reachable while Setup Wizard is open
        async with AsyncClient(transport=transport, base_url="https://new-hosting.example.org") as setup_client:
            r_root = await setup_client.get("/", follow_redirects=False)
            assert r_root.status_code == 307
            assert r_root.headers["location"] == "/setup"

            r_page = await setup_client.get("/setup")
            assert r_page.status_code == 200
            assert "Початкове налаштування SD-GEN016" in r_page.text

            r_probe = await setup_client.post(
                "/api/v1/setup/test-db",
                json={"db_type": "sqlite", "sqlite_filename": wizard_db_name},
            )
            assert r_probe.status_code == 200
            assert r_probe.json()["ok"] is True

            r_done = await setup_client.post(
                "/api/v1/setup/complete",
                json={
                    "db_type": "sqlite",
                    "sqlite_filename": wizard_db_name,
                    "organization_name": "Solar Backup Corp",
                    "primary_domain": "new-hosting.example.org",
                    "facility_timezone": "Europe/Kyiv",
                    "facility_name": "Main Plant",
                    "facility_address": "Kyiv, 1",
                    "admin_login": "owner_admin",
                    "admin_email": "owner@example.org",
                    "admin_full_name": "System Owner",
                    "admin_password": "WizardStrongPassword123!",
                    "openweather_api_key": "owm_wiz_secret_99",
                },
            )
            assert r_done.status_code == 200
            assert r_done.json()["status"] == "ok"
            assert is_setup_required() is False

            # Wizard is now permanently locked (403 on replay)
            r_replay = await setup_client.post(
                "/api/v1/setup/complete",
                json={
                    "db_type": "sqlite",
                    "sqlite_filename": wizard_db_name,
                    "organization_name": "Hack",
                    "admin_login": "hack2",
                    "admin_email": "hack2@example.org",
                    "admin_full_name": "Hack",
                    "admin_password": "WizardStrongPassword123!",
                },
            )
            assert r_replay.status_code == 403

        # Verify persisted instance.config.json
        cfg = load_instance_config(cfg_path)
        assert cfg["setup_completed"] is True
        assert len(cfg["app_secret_key"]) >= 32
        assert wizard_db_name in cfg["database_url"]

        # Verify SuperAdmin and encrypted API key in newly initialized DB
        async with AsyncSessionLocal() as db:
            user = (await db.execute(select(User).where(User.login == "owner_admin"))).scalars().first()
            assert user is not None
            assert user.is_superadmin is True
            assert verify_password("WizardStrongPassword123!", user.password_hash) is True

            owm_row = (
                await db.execute(select(SystemSetting).where(SystemSetting.key == "openweather_api_key"))
            ).scalars().first()
            assert json.loads(owm_row.value_json).startswith(ENC_PREFIX)
    finally:
        set_setup_required(False)
        set_runtime_setting("primary_domain", "")
        set_runtime_setting("openweather_api_key", "")
        settings.APP_SECRET_KEY = orig_secret
        await reinit_database_engine(orig_db_url)
        if data_db_path.exists():
            try:
                data_db_path.unlink()
            except OSError:
                pass


@pytest.mark.asyncio
async def test_migrate_zero_env_endpoint_requires_superadmin_and_writes_instance_config(
    client, operator_auth, admin_auth, superadmin_auth, tmp_path, monkeypatch
):
    cfg_path = tmp_path / "instance.config.json"
    monkeypatch.setenv("SDGEN_INSTANCE_CONFIG", str(cfg_path))

    for headers in (operator_auth, admin_auth):
        r_denied = await client.post("/api/v1/system/server-config/migrate-zero-env", headers=headers)
        assert r_denied.status_code == 403

    r_ok = await client.post("/api/v1/system/server-config/migrate-zero-env", headers=superadmin_auth)
    assert r_ok.status_code == 200
    body = r_ok.json()
    assert body["runtime"]["bootstrap_mode"] == "instance_config"
    assert body["runtime"]["instance_config_exists"] is True
    assert body["runtime"]["setup_completed"] is True

    saved = load_instance_config(cfg_path)
    assert saved["setup_completed"] is True
    assert saved["app_secret_key"] == settings.APP_SECRET_KEY
