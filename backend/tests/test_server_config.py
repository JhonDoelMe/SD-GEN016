"""Tests for centralized Server & Integrations settings, encryption at rest, RBAC, and dynamic runtime resolution."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import select

from backend.app.config import settings
from backend.app.core.secrets import (
    ENC_PREFIX,
    SECRET_MASK,
    decrypt_secret,
    encrypt_secret,
    is_encrypted_secret,
    mask_secret,
)
from backend.app.models.audit import AuditLog
from backend.app.models.settings import SystemSetting
from backend.app.services.fcm_service import _load_service_account, reset_fcm_token_cache
from backend.app.services.settings_service import (
    SERVER_ONLY_SETTING_KEYS,
    get_effective_allowed_hosts,
    get_effective_cors_origins,
    get_effective_int_setting,
    get_effective_primary_domain,
    get_effective_str_setting,
    get_runtime_setting,
    load_system_settings,
    set_runtime_setting,
    update_system_settings,
)


def test_secret_encryption_roundtrip_and_legacy_plaintext():
    plain = "super_api_key_2026_!@#"
    enc = encrypt_secret(plain)
    assert enc.startswith(ENC_PREFIX)
    assert enc != plain
    assert is_encrypted_secret(enc) is True
    assert decrypt_secret(enc) == plain

    # Idempotence: already encrypted values are not double-encrypted
    assert encrypt_secret(enc) == enc

    # Backward compatibility: legacy unencrypted rows still decrypt to plaintext
    assert decrypt_secret("legacy_plain_secret") == "legacy_plain_secret"
    assert mask_secret(enc) == SECRET_MASK
    assert mask_secret("") == ""


@pytest.mark.asyncio
async def test_legacy_plaintext_secret_auto_upgrades_to_encrypted_in_db(db_session):
    await load_system_settings(db_session)
    row = (
        await db_session.execute(select(SystemSetting).where(SystemSetting.key == "openweather_api_key"))
    ).scalars().first()
    row.value_json = json.dumps("legacy_owm_secret_123")
    await db_session.commit()

    loaded = await load_system_settings(db_session)
    assert loaded["openweather_api_key"] == "legacy_owm_secret_123"

    refreshed_row = (
        await db_session.execute(select(SystemSetting).where(SystemSetting.key == "openweather_api_key"))
    ).scalars().first()
    raw_stored = json.loads(refreshed_row.value_json)
    assert raw_stored.startswith(ENC_PREFIX)
    assert decrypt_secret(raw_stored) == "legacy_owm_secret_123"

    # Cleanup
    await update_system_settings(db_session, {"openweather_api_key": ""})


@pytest.mark.asyncio
async def test_server_config_rbac_rejects_operator_and_admin(client, operator_auth, admin_auth):
    for headers in (operator_auth, admin_auth):
        r_get = await client.get("/api/v1/system/server-config", headers=headers)
        assert r_get.status_code == 403

        r_put = await client.put("/api/v1/system/server-config", headers=headers, json={"primary_domain": "evil.com"})
        assert r_put.status_code == 403

        r_test = await client.post(
            "/api/v1/system/server-config/test-integration",
            headers=headers,
            json={"provider": "openweather"},
        )
        assert r_test.status_code == 403


@pytest.mark.asyncio
async def test_regular_admin_settings_endpoint_excludes_server_only_keys(client, admin_auth):
    res = await client.get("/api/v1/system/settings", headers=admin_auth)
    assert res.status_code == 200
    payload = res.json()["settings"]
    for key in SERVER_ONLY_SETTING_KEYS:
        assert key not in payload


@pytest.mark.asyncio
async def test_superadmin_server_config_encrypts_masks_and_updates_runtime(client, superadmin_auth, db_session):
    sa_payload = {
        "type": "service_account",
        "project_id": "sdgen-cms-test",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC\n-----END PRIVATE KEY-----\n",
        "client_email": "firebase-adminsdk@sdgen-cms-test.iam.gserviceaccount.com",
    }

    try:
        res_put = await client.put(
            "/api/v1/system/server-config",
            headers=superadmin_auth,
            json={
                "primary_domain": "https://portal.example.ua/",
                "openweather_api_key": "owm_secret_xyz",
                "alerts_in_ua_token": "aiu_secret_token",
                "access_token_expire_minutes": 720,
                "firebase_service_account_json": json.dumps(sa_payload),
            },
        )
        assert res_put.status_code == 200
        body = res_put.json()
        cfg = body["config"]
        assert cfg["primary_domain"] == "portal.example.ua"
        assert cfg["openweather_api_key"] == SECRET_MASK
        assert cfg["alerts_in_ua_token"] == SECRET_MASK
        assert cfg["firebase_service_account_json"] == SECRET_MASK
        assert cfg["firebase_configured"] is True
        assert cfg["firebase_project_id"] == "sdgen-cms-test"
        assert body["sources"]["openweather_api_key"] == "db"
        assert body["sources"]["primary_domain"] == "db"

        # DB row must hold encrypted value, not plaintext
        owm_row = (
            await db_session.execute(select(SystemSetting).where(SystemSetting.key == "openweather_api_key"))
        ).scalars().first()
        owm_stored = json.loads(owm_row.value_json)
        assert owm_stored.startswith(ENC_PREFIX)
        assert "owm_secret_xyz" not in owm_stored

        # Runtime helpers resolve new DB overrides immediately
        assert get_effective_primary_domain() == "portal.example.ua"
        assert get_effective_str_setting("openweather_api_key") == "owm_secret_xyz"
        assert get_effective_int_setting("access_token_expire_minutes", default=1440) == 720
        assert "portal.example.ua" in get_effective_allowed_hosts()
        assert "https://portal.example.ua" in get_effective_cors_origins()
        loaded_sa = _load_service_account()
        assert loaded_sa is not None and loaded_sa["project_id"] == "sdgen-cms-test"

        # Submitting SECRET_MASK preserves underlying DB secrets
        res_preserve = await client.put(
            "/api/v1/system/server-config",
            headers=superadmin_auth,
            json={
                "openweather_api_key": SECRET_MASK,
                "alerts_in_ua_token": "",
                "weather_cache_minutes": 30,
            },
        )
        assert res_preserve.status_code == 200
        assert get_runtime_setting("openweather_api_key") == "owm_secret_xyz"
        assert get_runtime_setting("alerts_in_ua_token") == "aiu_secret_token"

        # Dynamic primary_domain reflects in /api/health and index HTML meta tag
        r_health = await client.get("/api/health")
        assert r_health.status_code == 200
        assert r_health.json()["primary_domain"] == "portal.example.ua"

        # Audit log never records plaintext secrets
        audit_row = (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "SERVER_CONFIG_UPDATED").order_by(AuditLog.id.desc())
            )
        ).scalars().first()
        assert audit_row is not None
        assert "owm_secret_xyz" not in (audit_row.details_json or "")
        assert "BEGIN PRIVATE KEY" not in (audit_row.details_json or "")

        # Clearing keys restores empty/default fallback
        res_clear = await client.put(
            "/api/v1/system/server-config",
            headers=superadmin_auth,
            json={"clear_keys": ["openweather_api_key", "firebase_service_account_json", "primary_domain"]},
        )
        assert res_clear.status_code == 200
        assert get_runtime_setting("openweather_api_key") == ""
        assert get_effective_primary_domain() == settings.PRIMARY_DOMAIN
    finally:
        # Ensure clean runtime state for subsequent tests
        await client.put(
            "/api/v1/system/server-config",
            headers=superadmin_auth,
            json={
                "clear_keys": [
                    "primary_domain",
                    "allowed_hosts",
                    "cors_origins",
                    "access_token_expire_minutes",
                    "openweather_api_key",
                    "weather_cache_minutes",
                    "alerts_in_ua_token",
                    "ukraine_alarm_api_key",
                    "alerts_cache_seconds",
                    "ukraine_alarm_cache_seconds",
                    "firebase_service_account_json",
                ]
            },
        )
        set_runtime_setting("primary_domain", "")
        reset_fcm_token_cache()


@pytest.mark.asyncio
async def test_server_config_rejects_invalid_firebase_json_and_tests_openweather(client, superadmin_auth):
    r_bad = await client.put(
        "/api/v1/system/server-config",
        headers=superadmin_auth,
        json={"firebase_service_account_json": "{not valid json"},
    )
    assert r_bad.status_code == 400

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"main": {"temp": 14.5}}

    with patch("backend.app.api.v1.system.httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
        r_test = await client.post(
            "/api/v1/system/server-config/test-integration",
            headers=superadmin_auth,
            json={"provider": "openweather", "value": "probe_key_123"},
        )
    assert r_test.status_code == 200
    assert r_test.json()["status"] == "ok"
    assert "14.5" in r_test.json()["message"]
