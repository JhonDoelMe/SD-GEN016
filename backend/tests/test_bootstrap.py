"""Tests for Stage 2 Zero-.env bootstrap config, secret generation, and dynamic DB engine switching."""

import json
from sqlalchemy import text
import pytest

from backend.app.config import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_DATABASE_URL,
    DEFAULT_SECRET_KEY,
    Settings,
    settings,
)
from backend.app.core.bootstrap import (
    instance_config_exists,
    is_setup_completed,
    load_instance_config,
    save_instance_config,
    update_instance_config,
)
from backend.app.database import (
    AsyncSessionLocal,
    probe_database_connection,
    reinit_database_engine,
)


def test_bootstrap_auto_generates_and_reuses_secret(tmp_path):
    cfg_path = tmp_path / "data" / "instance.config.json"

    s1 = Settings(
        APP_ENV="development",
        APP_SECRET_KEY=DEFAULT_SECRET_KEY,
        DATABASE_URL=DEFAULT_DATABASE_URL,
    )
    assert s1.apply_bootstrap_config(config_path=cfg_path, auto_generate_secret=True) is True
    assert len(s1.APP_SECRET_KEY) >= 64
    assert s1.APP_SECRET_KEY != DEFAULT_SECRET_KEY
    assert cfg_path.is_file()

    # Second instance loads the exact same persisted secret key
    s2 = Settings(
        APP_ENV="development",
        APP_SECRET_KEY=DEFAULT_SECRET_KEY,
        DATABASE_URL=DEFAULT_DATABASE_URL,
    )
    assert s2.apply_bootstrap_config(config_path=cfg_path, auto_generate_secret=True) is True
    assert s2.APP_SECRET_KEY == s1.APP_SECRET_KEY


def test_bootstrap_respects_explicit_env_overrides(tmp_path):
    cfg_path = tmp_path / "instance.config.json"
    save_instance_config(
        {
            "app_secret_key": "Z" * 64,
            "database_url": "sqlite+aiosqlite:///./from_bootstrap.db",
            "setup_completed": True,
        },
        config_path=cfg_path,
    )

    explicit_env = Settings(
        APP_ENV="production",
        APP_SECRET_KEY="E" * 48,
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/prod_db",
        INITIAL_ADMIN_PASSWORD="ExplicitProdPassword999!",
    )
    # Explicit env values take priority over instance.config.json
    applied = explicit_env.apply_bootstrap_config(config_path=cfg_path, auto_generate_secret=False)
    assert applied is False
    assert explicit_env.APP_SECRET_KEY == "E" * 48
    assert explicit_env.DATABASE_URL == "postgresql+asyncpg://u:p@localhost:5432/prod_db"


def test_bootstrap_applies_database_url_and_prod_lock_when_setup_completed(tmp_path):
    cfg_path = tmp_path / "instance.config.json"
    update_instance_config(
        {
            "app_secret_key": "B" * 64,
            "database_url": f"sqlite+aiosqlite:///{(tmp_path / 'zero_env.db').as_posix()}",
            "setup_completed": True,
            "app_env": "production",
        },
        config_path=cfg_path,
    )

    s = Settings(
        APP_ENV="development",
        APP_SECRET_KEY=DEFAULT_SECRET_KEY,
        DATABASE_URL=DEFAULT_DATABASE_URL,
        INITIAL_ADMIN_PASSWORD=DEFAULT_ADMIN_PASSWORD,
    )
    assert s.apply_bootstrap_config(config_path=cfg_path, auto_generate_secret=False) is True
    assert s.APP_ENV == "production"
    assert s.APP_SECRET_KEY == "B" * 64
    assert "zero_env.db" in s.DATABASE_URL
    assert is_setup_completed(cfg_path) is True
    assert instance_config_exists(cfg_path) is True

    # Setup not marked initialized -> still blocks default admin password in production
    with pytest.raises(RuntimeError, match="INITIAL_ADMIN_PASSWORD"):
        s.check_security_warnings(has_initialized_admin=False)

    # Setup completed (admin exists in DB) + strong generated APP_SECRET_KEY -> allowed
    s.check_security_warnings(has_initialized_admin=True)

    # Weak APP_SECRET_KEY is STILL strictly blocked even if admin is initialized
    s.APP_SECRET_KEY = DEFAULT_SECRET_KEY
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        s.check_security_warnings(has_initialized_admin=True)


@pytest.mark.asyncio
async def test_database_connection_probe_and_dynamic_reinit(tmp_path):
    probe_db = tmp_path / "nested" / "probe.db"
    ok, msg = await probe_database_connection(f"sqlite+aiosqlite:///{probe_db.as_posix()}")
    assert ok is True
    assert "SQLite" in msg
    assert probe_db.parent.exists()

    # Failing connection probe scrubs credentials from error text
    bad_ok, bad_msg = await probe_database_connection(
        "postgresql+asyncpg://admin:UltraSecretPass123@127.0.0.1:59999/nope",
        timeout_sec=1.0,
    )
    assert bad_ok is False
    assert "UltraSecretPass123" not in bad_msg

    # Verify dynamic reinit switches engine cleanly and restores previous DB
    orig_url = settings.DATABASE_URL
    alt_db = tmp_path / "reinit_test.db"
    try:
        dialect = await reinit_database_engine(f"sqlite+aiosqlite:///{alt_db.as_posix()}")
        assert dialect == "sqlite"
        async with AsyncSessionLocal() as sess:
            res = await sess.execute(text("SELECT 1"))
            assert res.scalar() == 1
    finally:
        await reinit_database_engine(orig_url)


@pytest.mark.asyncio
async def test_server_config_runtime_reports_bootstrap_status(client, superadmin_auth):
    res = await client.get("/api/v1/system/server-config", headers=superadmin_auth)
    assert res.status_code == 200
    rt = res.json()["runtime"]
    assert rt["bootstrap_mode"] in ("env", "instance_config")
    assert isinstance(rt["instance_config_exists"], bool)
    assert isinstance(rt["setup_completed"], bool)
