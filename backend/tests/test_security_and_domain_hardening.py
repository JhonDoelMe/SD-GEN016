import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from sqlalchemy import select

from backend.app.config import settings
from backend.app.core.security import decode_access_token
from backend.app.models.canister import CanisterPool
from backend.app.models.fuel import FuelStock
from backend.app.models.generator import Generator
from backend.app.models.idempotency import IdempotencyRecord
from backend.app.models.measurement import FuelMeasurement
from backend.app.models.user import PasswordResetToken, User
from backend.app.services.backup_service import (
    SENSITIVE_ENV_KEYWORDS,
    TABLE_ORDER,
    _copy_env_redacted,
    create_backup,
)
from backend.app.services.email_service import validate_smtp_target


@pytest.mark.asyncio
async def test_unbound_non_admin_fail_closed_403(client, superadmin_auth):
    """Non-admin user with facility_id=None must fail closed with 403 on tenant endpoints."""
    create_res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "unbound_op",
            "password": "UnboundOpPass123!",
            "full_name": "Неприв'язаний Оператор",
            "role_ids": [3],
            "facility_id": None,
        },
    )
    assert create_res.status_code == 201, create_res.text

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"login": "unbound_op", "password": "UnboundOpPass123!", "remember_me": False},
    )
    assert login_res.status_code == 200
    headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}
    client.cookies.clear()

    r_receipt = await client.post(
        "/api/v1/fuel/receipt",
        headers=headers,
        json={
            "liters": 10.0,
            "price_per_liter": 55.0,
            "driver_name": "Тестовий Водій",
            "receipt_number": "CHK-001",
        },
    )
    assert r_receipt.status_code == 403

    r_transfer = await client.post(
        "/api/v1/fuel/transfer",
        headers=headers,
        json={"liters": 5.0},
    )
    assert r_transfer.status_code == 403

    r_logs = await client.get("/api/v1/notifications/logs", headers=headers)
    assert r_logs.status_code == 403

    r_adj = await client.get("/api/v1/adjustments", headers=headers)
    assert r_adj.status_code == 403

    r_gen = await client.post("/api/v1/generator/start", headers=headers, json={})
    assert r_gen.status_code == 403


def test_smtp_ssrf_target_validation():
    """SSRF target validator blocks localhost, .local, cloud metadata, and invalid ports."""
    for bad_host, bad_port in [
        ("127.0.0.1", 587),
        ("localhost", 587),
        ("metadata.google.internal", 587),
        ("169.254.169.254", 587),
        ("insecure.smtp.local", 587),
        ("smtp.gmail.com", 22),
    ]:
        with pytest.raises(ValueError):
            validate_smtp_target(bad_host, bad_port)

    validate_smtp_target("smtp.gmail.com", 587)
    validate_smtp_target("smtp.gmail.com", 465)


@pytest.mark.asyncio
async def test_smtp_test_rejects_ssrf_without_mutating_global_setting(client, superadmin_auth):
    """Testing email with internal SSRF host returns 400 and does not mutate smtp_enabled."""
    res = await client.post(
        "/api/v1/system/email/test",
        headers=superadmin_auth,
        json={
            "recipient": "admin@example.com",
            "provider": "primary",
            "smtp_primary_host": "127.0.0.1",
            "smtp_primary_port": 587,
        },
    )
    assert res.status_code == 400

    cfg = await client.get("/api/v1/system/settings", headers=superadmin_auth)
    assert cfg.status_code == 200
    assert cfg.json().get("smtp_enabled") is not True


@pytest.mark.asyncio
async def test_change_password_preserves_remember_me_and_revokes_old_token(client, superadmin_auth):
    """Changing own password preserves rem claim and revokes old access token."""
    u_res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "rem_tester",
            "password": "StartPass123!",
            "full_name": "Rem Tester",
            "role_ids": [3],
            "facility_id": 1,
        },
    )
    assert u_res.status_code == 201

    for rem_flag in (False, True):
        cur_pass = "StartPass123!" if not rem_flag else "NextPass123!"
        new_pass = "NextPass123!" if not rem_flag else "FinalPass123!"
        l_res = await client.post(
            "/api/v1/auth/login",
            json={"login": "rem_tester", "password": cur_pass, "remember_me": rem_flag},
        )
        assert l_res.status_code == 200
        old_tok = l_res.json()["access_token"]
        old_hdrs = {"Authorization": f"Bearer {old_tok}"}
        client.cookies.clear()

        chg_res = await client.post(
            "/api/v1/auth/change-password",
            headers=old_hdrs,
            json={"current_password": cur_pass, "new_password": new_pass},
        )
        assert chg_res.status_code == 200, chg_res.text
        new_tok = chg_res.json()["access_token"]
        decoded = decode_access_token(new_tok)
        assert decoded is not None
        assert bool(decoded.get("rem", False)) is rem_flag

        # Old token must be revoked immediately
        client.cookies.clear()
        me_old = await client.get("/api/v1/auth/me", headers=old_hdrs)
        assert me_old.status_code == 401


@pytest.mark.asyncio
async def test_backup_redacts_secrets_and_skips_service_accounts(db_session, tmp_path, monkeypatch):
    """Backup env redaction masks sensitive vars while preserving safe settings, and config backup excludes secrets."""
    src_env = tmp_path / ".env"
    src_env.write_text(
        "SECRET_KEY=super-secret-value\nSMTP_PASSWORD=mail-pass\nFIREBASE_PRIVATE_KEY=priv\nTIMEZONE=Europe/Kyiv\n",
        encoding="utf-8",
    )
    dst_env = tmp_path / ".env.redacted"
    _copy_env_redacted(src_env, dst_env)
    redacted_text = dst_env.read_text(encoding="utf-8")
    assert "super-secret-value" not in redacted_text
    assert "mail-pass" not in redacted_text
    assert "priv" not in redacted_text
    assert "TIMEZONE=Europe/Kyiv" in redacted_text

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(uploads_dir))

    meta = await create_backup(db_session, backup_type="config", creator="test")
    archive_path = backup_dir / meta["filename"]
    assert archive_path.is_file()

    with zipfile.ZipFile(archive_path, "r") as zf:
        names = zf.namelist()
        assert not any("service-account" in n or "firebase-service-account" in n or n.endswith(".p12") for n in names)

    table_models = [cls for _, cls in TABLE_ORDER]
    assert PasswordResetToken in table_models
    assert IdempotencyRecord in table_models
    assert "PRIVATE" in SENSITIVE_ENV_KEYWORDS
    assert "KEY" in SENSITIVE_ENV_KEYWORDS
    assert "TOKEN" in SENSITIVE_ENV_KEYWORDS


@pytest.mark.asyncio
async def test_canister_pool_nonzero_stock_and_deactivate_and_receive_idempotency(
    client, db_session, superadmin_auth
):
    """Canister creation rejects mismatch on non-zero stock, rejects deactivating non-empty pool, and deduplicates receive."""
    st_res = await client.post(
        "/api/v1/fuel/stocks",
        headers=superadmin_auth,
        json={"facility_id": 1, "name": "Склад-Тест-Каністр", "fuel_type": "А-95", "initial_balance_l": 50.0},
    )
    assert st_res.status_code == 201
    stock_id = st_res.json()["id"]

    # Creating first pool whose liters (20L) != non-zero stock balance (50L) must be rejected
    bad_pool = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": 1,
            "stock_id": stock_id,
            "name": "Каністри 20л",
            "canister_volume_l": 20.0,
            "full_count": 1,
            "empty_count": 0,
            "away_refill_count": 0,
            "reserve_liters": 0.0,
        },
    )
    assert bad_pool.status_code == 400

    # Creating pool with matching 0L stock & 1x20L + 1 empty + 1 away -> first let's make empty stock
    st_empty = await client.post(
        "/api/v1/fuel/stocks",
        headers=superadmin_auth,
        json={"facility_id": 1, "name": "Склад-Нуль", "fuel_type": "А-95", "initial_balance_l": 0.0},
    )
    assert st_empty.status_code == 201
    stock0_id = st_empty.json()["id"]

    ok_pool = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": 1,
            "stock_id": stock0_id,
            "name": "Каністри Нуль-Старт",
            "canister_volume_l": 20.0,
            "full_count": 1,
            "empty_count": 1,
            "away_refill_count": 1,
            "reserve_liters": 0.0,
        },
    )
    assert ok_pool.status_code == 201
    pool_id = ok_pool.json()["id"]

    # Cannot deactivate pool while it has full_count=1
    deact_res = await client.put(
        f"/api/v1/fuel/canisters/{pool_id}",
        headers=superadmin_auth,
        json={"is_active": False},
    )
    assert deact_res.status_code == 400

    # Receive with Idempotency-Key must not double credit stock on replay
    idem_hdrs = {**superadmin_auth, "Idempotency-Key": "receive-replay-001"}
    r1 = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/receive",
        headers=idem_hdrs,
        json={"count": 1, "source": "away", "create_receipt": True},
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/receive",
        headers=idem_hdrs,
        json={"count": 1, "source": "away", "create_receipt": True},
    )
    assert r2.status_code == 200
    assert r2.json()["full_count"] == 2
    st_after = await db_session.get(FuelStock, stock0_id)
    assert st_after.current_balance_l == pytest.approx(40.0)


@pytest.mark.asyncio
async def test_delete_facility_or_generator_blocked_during_active_measurement(client, db_session, superadmin_auth):
    """Deleting a generator or non-default facility is blocked while a measurement is active."""
    fac_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={"name": "Локація Заміру", "code": "MEAS-F1", "timezone": "Europe/Kyiv"},
    )
    assert fac_res.status_code in (200, 201), fac_res.text
    fac_id = fac_res.json()["id"]

    gen_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "name": "Ген Заміру",
            "model": "KS-9000iE",
            "manufacturer": "Konner",
            "serial_number": "SN-DEL-001",
            "rated_power_kw": 7.5,
            "tank_capacity_l": 40.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 10.0,
            "initial_fuel_tank_level_l": 40.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert gen_res.status_code == 200
    gen_id = gen_res.json()["id"]

    st_res = await client.post(
        "/api/v1/measurement/start",
        headers=superadmin_auth,
        json={"facility_id": fac_id, "generator_id": gen_id},
    )
    assert st_res.status_code == 200, st_res.text

    del_gen = await client.delete(f"/api/v1/generator/{gen_id}", headers=superadmin_auth)
    assert del_gen.status_code == 400

    del_fac = await client.delete(f"/api/v1/facilities/{fac_id}", headers=superadmin_auth)
    assert del_fac.status_code == 400


@pytest.mark.asyncio
async def test_avatar_decompression_bomb_rejected(client, superadmin_auth, tmp_path, monkeypatch):
    """Huge-dimension image fails avatar pixel guard cleanly with 400."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    # Tiny PNG compressed solid white 6000x6000 = 36M pixels (> 25M limit)
    buf = io.BytesIO()
    img = Image.new("RGB", (6000, 6000), color="white")
    img.save(buf, format="PNG")
    buf.seek(0)

    res = await client.post(
        "/api/v1/auth/me/avatar",
        headers=superadmin_auth,
        files={"file": ("huge.png", buf, "image/png")},
    )
    assert res.status_code == 400
