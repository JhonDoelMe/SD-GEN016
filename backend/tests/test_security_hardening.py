import zipfile
import pytest
from pathlib import Path

from backend.app.config import settings
from backend.app.services.init_service import seed_initial_data
from backend.app.services.backup_service import _copy_env_redacted, _safe_extract_zip


@pytest.mark.asyncio
async def test_self_service_password_change_and_jwt_invalidation(client, operator_auth):
    # 1. Verify current token works
    me_res = await client.get("/api/v1/auth/me", headers=operator_auth)
    assert me_res.status_code == 200

    # 2. Change password with wrong current password -> 400
    bad_res = await client.post(
        "/api/v1/auth/change-password",
        headers=operator_auth,
        json={"current_password": "WrongOldPassword!", "new_password": "NewOperatorPass456!"}
    )
    assert bad_res.status_code == 400

    # 3. Change password with valid current password -> 200
    ok_res = await client.post(
        "/api/v1/auth/change-password",
        headers=operator_auth,
        json={"current_password": "OperatorPass123!", "new_password": "NewOperatorPass456!"}
    )
    assert ok_res.status_code == 200

    # 4. Old JWT token must now be rejected (pwd_sig mismatch)
    old_token_res = await client.get("/api/v1/auth/me", headers=operator_auth)
    assert old_token_res.status_code == 401

    # 5. Login with new password succeeds and returns working token
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"login": "operator1", "password": "NewOperatorPass456!"}
    )
    assert login_res.status_code == 200
    new_token = login_res.json()["access_token"]
    new_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_me.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_jwt_token(client, operator_auth):
    # Token works before logout
    me_res = await client.get("/api/v1/auth/me", headers=operator_auth)
    assert me_res.status_code == 200

    # Logout
    logout_res = await client.post("/api/v1/auth/logout", headers=operator_auth)
    assert logout_res.status_code == 200

    # Same token is immediately rejected after logout
    after_res = await client.get("/api/v1/auth/me", headers=operator_auth)
    assert after_res.status_code == 401


@pytest.mark.asyncio
async def test_superadmin_password_preserved_on_restart(client, db_session, superadmin_auth):
    # SuperAdmin changes own password
    res = await client.post(
        "/api/v1/auth/change-password",
        headers=superadmin_auth,
        json={"current_password": settings.INITIAL_ADMIN_PASSWORD, "new_password": "SuperSecureNewPass!2026"}
    )
    assert res.status_code == 200

    # Simulate server restart by running seed_initial_data again
    await seed_initial_data(db_session)

    # SuperAdmin's new password must STILL work (not overwritten by .env)
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"login": settings.INITIAL_ADMIN_LOGIN.strip(), "password": "SuperSecureNewPass!2026"}
    )
    assert login_res.status_code == 200


@pytest.mark.asyncio
async def test_bruteforce_protection_resistant_to_xff_spoofing(client, operator_auth):
    # Attempt 5 failed logins rotating spoofed X-Forwarded-For headers
    for i in range(5):
        r = await client.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": f"203.0.113.{i + 10}, 198.51.100.{i + 1}"},
            json={"login": "operator1", "password": "WrongPassword123"}
        )
        assert r.status_code == 401

    # 6th attempt even with a brand new spoofed X-Forwarded-For must be blocked with 429
    r6 = await client.post(
        "/api/v1/auth/login",
        headers={"X-Forwarded-For": "192.0.2.99"},
        json={"login": "operator1", "password": "OperatorPass123!"}
    )
    assert r6.status_code == 429


@pytest.mark.asyncio
async def test_explicit_nonexistent_generator_id_returns_404(client, superadmin_auth):
    # Default generator fallback (when generator_id is omitted) still works (200)
    default_res = await client.get("/api/v1/generator", headers=superadmin_auth)
    assert default_res.status_code == 200

    # Explicit non-existent generator_id=99999 must return 404 Not Found
    not_found_status = await client.get("/api/v1/generator?generator_id=99999", headers=superadmin_auth)
    assert not_found_status.status_code == 404

    not_found_maint = await client.get("/api/v1/maintenance/schedule?generator_id=99999", headers=superadmin_auth)
    assert not_found_maint.status_code == 404


@pytest.mark.asyncio
async def test_multisite_facility_isolation_variant_b(client, superadmin_auth, admin_auth, operator_auth):
    # SuperAdmin creates Facility #2 and a Generator on Facility #2
    fac_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={"name": "Другий Об'єкт Ізольований", "address": "вул. Безпеки 2"}
    )
    assert fac_res.status_code == 201
    fac2_id = fac_res.json()["id"]

    gen_res = await client.post(
        "/api/v1/generator",
        headers=superadmin_auth,
        json={
            "facility_id": fac2_id,
            "name": "Генератор Об'єкта 2",
            "model": "Honda EU30i",
            "manufacturer": "Honda",
            "serial_number": "SN-FAC2-001",
            "rated_power_kw": 3.0,
            "tank_capacity_l": 13.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 1.5
        }
    )
    assert gen_res.status_code == 201
    gen2_id = gen_res.json()["id"]

    # Operator1 (assigned to facility_id=1) can access Facility #1
    op_fac1 = await client.get("/api/v1/facilities/1", headers=operator_auth)
    assert op_fac1.status_code == 200

    # Operator1 CANNOT access Facility #2 details or Generator on Facility #2 -> 403 Forbidden
    op_fac2 = await client.get(f"/api/v1/facilities/{fac2_id}", headers=operator_auth)
    assert op_fac2.status_code == 403

    op_gen2 = await client.get(f"/api/v1/generator?generator_id={gen2_id}", headers=operator_auth)
    assert op_gen2.status_code == 403

    op_fuel2 = await client.get(f"/api/v1/fuel/stock?facility_id={fac2_id}", headers=operator_auth)
    assert op_fuel2.status_code == 403

    # Admin and SuperAdmin CAN access Facility #2 and Generator #2 -> 200 OK
    adm_fac2 = await client.get(f"/api/v1/facilities/{fac2_id}", headers=admin_auth)
    assert adm_fac2.status_code == 200

    adm_gen2 = await client.get(f"/api/v1/generator?generator_id={gen2_id}", headers=admin_auth)
    assert adm_gen2.status_code == 200


@pytest.mark.asyncio
async def test_webpush_ssrf_and_idor_protection(client, operator_auth, viewer_auth):
    # 1. SSRF: Reject HTTP or internal/untrusted endpoints
    for unsafe_url in [
        "http://fcm.googleapis.com/fcm/send/abc",
        "https://127.0.0.1:8080/push",
        "https://169.254.169.254/latest/meta-data/",
        "https://localhost/push",
        "https://evil-attacker-server.com/webpush"
    ]:
        bad_sub = await client.post(
            "/api/v1/notifications/subscribe",
            headers=operator_auth,
            json={
                "endpoint": unsafe_url,
                "keys": {"p256dh": "valid_p256dh_key_12345", "auth": "valid_auth_123"}
            }
        )
        assert bad_sub.status_code == 422, f"Expected 422 for {unsafe_url}, got {bad_sub.status_code}"

    # 2. Trusted Web Push endpoint succeeds
    good_endpoint = "https://fcm.googleapis.com/fcm/send/operator1-device-token"
    ok_sub = await client.post(
        "/api/v1/notifications/subscribe",
        headers=operator_auth,
        json={
            "endpoint": good_endpoint,
            "keys": {"p256dh": "valid_p256dh_key_12345", "auth": "valid_auth_123"}
        }
    )
    assert ok_sub.status_code in (200, 201)

    # 3. IDOR: viewer1 cannot unsubscribe operator1's endpoint (returns 403 Forbidden)
    idor_unsub = await client.post(
        "/api/v1/notifications/unsubscribe",
        headers=viewer_auth,
        json={"endpoint": good_endpoint}
    )
    assert idor_unsub.status_code in (403, 404)

    # 4. Operator1 can unsubscribe own endpoint
    own_unsub = await client.post(
        "/api/v1/notifications/unsubscribe",
        headers=operator_auth,
        json={"endpoint": good_endpoint}
    )
    assert own_unsub.status_code == 200


def test_env_redaction_and_zip_slip_protection(tmp_path: Path):
    # 1. Test _copy_env_redacted masks secrets
    src_env = tmp_path / ".env"
    dst_env = tmp_path / ".env.redacted"
    src_env.write_text(
        "PRIMARY_DOMAIN=generator-016.pp.ua\n"
        "APP_SECRET_KEY=MySuperSecretKey12345\n"
        "INITIAL_ADMIN_PASSWORD=AdminSecretPass!\n"
        "POSTGRES_PASSWORD=DbPass999\n"
        "FACILITY_TIMEZONE=Europe/Kyiv\n",
        encoding="utf-8"
    )
    _copy_env_redacted(src_env, dst_env)
    redacted_text = dst_env.read_text(encoding="utf-8")
    assert "PRIMARY_DOMAIN=generator-016.pp.ua" in redacted_text
    assert "FACILITY_TIMEZONE=Europe/Kyiv" in redacted_text
    assert "MySuperSecretKey12345" not in redacted_text
    assert "AdminSecretPass!" not in redacted_text
    assert "DbPass999" not in redacted_text
    assert "APP_SECRET_KEY=***REDACTED***" in redacted_text

    # 2. Test _safe_extract_zip blocks Path Traversal (Zip Slip)
    malicious_zip = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious_zip, "w") as zf:
        zf.writestr("../../evil.txt", "pwned")

    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with zipfile.ZipFile(malicious_zip, "r") as zf:
        with pytest.raises(ValueError, match="Path Traversal|межі"):
            _safe_extract_zip(zf, extract_dir)
