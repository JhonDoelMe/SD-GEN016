import datetime
import hashlib
import smtplib
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy import select

from backend.app.config import settings
from backend.app.core.timezone import now_utc
from backend.app.core.security import create_access_token, clear_all_login_attempts
from backend.app.models.user import User, PasswordResetToken
from backend.app.models.notification import NotificationLog
from backend.app.services.settings_service import update_system_settings, set_runtime_setting
from backend.app.services.email_service import (
    send_email_with_failover,
    send_password_reset_email,
    send_password_changed_email,
    send_weekly_digest_email,
)


@pytest.mark.asyncio
async def test_send_smtp_primary_success(db_session):
    set_runtime_setting("smtp_enabled", True)
    set_runtime_setting("smtp_primary_host", "smtp.gmail.com")
    set_runtime_setting("smtp_primary_user", "test@gmail.com")
    set_runtime_setting("smtp_primary_password", "app_pass_123")

    with patch("backend.app.services.email_service.send_smtp_message_sync") as mock_send:
        mock_send.return_value = None

        res = await send_email_with_failover(
            to_addr="recipient@test.com",
            subject="Test Subject",
            html_body="<p>Test Body</p>",
            db=db_session
        )

        assert res["status"] == "ok"
        assert res["provider"] == "primary"
        assert res["host"] == "smtp.gmail.com"
        mock_send.assert_called_once()

    # Check notification log
    logs = (await db_session.execute(select(NotificationLog).where(NotificationLog.event_type == "EMAIL_SENT"))).scalars().all()
    assert len(logs) >= 1
    assert "recipient@test.com" in logs[-1].body


@pytest.mark.asyncio
async def test_send_smtp_failover_to_secondary(db_session):
    set_runtime_setting("smtp_enabled", True)
    set_runtime_setting("smtp_primary_host", "smtp.gmail.com")
    set_runtime_setting("smtp_primary_user", "test@gmail.com")
    set_runtime_setting("smtp_primary_password", "pass1")
    set_runtime_setting("smtp_fallback_enabled", True)
    set_runtime_setting("smtp_fallback_host", "smtp.ukr.net")
    set_runtime_setting("smtp_fallback_user", "test@ukr.net")
    set_runtime_setting("smtp_fallback_password", "pass2")

    def side_effect(host, *args, **kwargs):
        if "gmail" in host:
            raise smtplib.SMTPConnectError(421, b"Connection refused")
        return None

    with patch("backend.app.services.email_service.send_smtp_message_sync", side_effect=side_effect) as mock_send:
        res = await send_email_with_failover(
            to_addr="recipient@test.com",
            subject="Failover Test",
            html_body="<p>Failover Body</p>",
            db=db_session
        )

        assert res["status"] == "ok"
        assert res["provider"] == "fallback"
        assert res["host"] == "smtp.ukr.net"
        assert "warning" in res
        assert mock_send.call_count == 2

    # Check failover notification log
    logs = (await db_session.execute(select(NotificationLog).where(NotificationLog.event_type == "EMAIL_FAILOVER"))).scalars().all()
    assert len(logs) >= 1


@pytest.mark.asyncio
async def test_send_smtp_both_failed(db_session):
    set_runtime_setting("smtp_enabled", True)
    set_runtime_setting("smtp_primary_host", "smtp.gmail.com")
    set_runtime_setting("smtp_fallback_enabled", True)
    set_runtime_setting("smtp_fallback_host", "smtp.ukr.net")
    set_runtime_setting("smtp_fallback_user", "user@ukr.net")

    with patch("backend.app.services.email_service.send_smtp_message_sync", side_effect=smtplib.SMTPException("Network down")):
        res = await send_email_with_failover(
            to_addr="fail@test.com",
            subject="Both Fail",
            html_body="<p>Fail</p>",
            db=db_session
        )

        assert res["status"] == "error"
        assert "Основний" in res["error"]
        assert "Резервний" in res["error"]


@pytest.mark.asyncio
async def test_forgot_password_and_token_creation(client, db_session):
    clear_all_login_attempts()
    # Update superadmin email
    user = (await db_session.execute(select(User).where(User.login == settings.INITIAL_ADMIN_LOGIN.strip()))).scalars().first()
    user.email = "superadmin@maxi-ua.com"
    await db_session.commit()

    captured_tokens = []

    async def mock_send_reset(to_addr, user_name, reset_token, base_url, db=None):
        captured_tokens.append(reset_token)
        return {"status": "ok", "provider": "primary"}

    with patch("backend.app.api.v1.auth.send_password_reset_email", side_effect=mock_send_reset):
        # 1. Request password reset via email
        res = await client.post("/api/v1/auth/forgot-password", json={"login_or_email": "superadmin@maxi-ua.com"})
        assert res.status_code == 200
        assert "інструкції для відновлення" in res.json()["message"]
        assert len(captured_tokens) == 1

        raw_token = captured_tokens[0]
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        # Check DB token
        t_row = (await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))).scalars().first()
        assert t_row is not None
        assert t_row.user_id == user.id
        assert t_row.used is False
        assert t_row.expires_at > now_utc()

        # 2. Test rate limiting: max 3 attempts per window
        await client.post("/api/v1/auth/forgot-password", json={"login_or_email": "superadmin@maxi-ua.com"})
        await client.post("/api/v1/auth/forgot-password", json={"login_or_email": "superadmin@maxi-ua.com"})
        res_limit = await client.post("/api/v1/auth/forgot-password", json={"login_or_email": "superadmin@maxi-ua.com"})
        assert res_limit.status_code == 429
        assert "Retry-After" in res_limit.headers


@pytest.mark.asyncio
async def test_reset_password_flow_and_session_invalidation(client, db_session):
    clear_all_login_attempts()
    user = (await db_session.execute(select(User).where(User.login == settings.INITIAL_ADMIN_LOGIN.strip()))).scalars().first()
    user.email = "admin2@maxi-ua.com"
    await db_session.commit()

    # Create old token and verify it works
    old_access_token = create_access_token(
        {"sub": str(user.id), "login": user.login},
        password_hash=user.password_hash
    )
    res_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access_token}"})
    assert res_me.status_code == 200

    captured_tokens = []

    async def mock_send_reset(to_addr, user_name, reset_token, base_url, db=None):
        captured_tokens.append(reset_token)
        return {"status": "ok"}

    with patch("backend.app.api.v1.auth.send_password_reset_email", side_effect=mock_send_reset):
        await client.post("/api/v1/auth/forgot-password", json={"login_or_email": "admin2@maxi-ua.com"})
        assert len(captured_tokens) == 1
        raw_token = captured_tokens[0]

    # Reset password with valid token
    new_pass = "BrandNewSecurePass2026!"
    with patch("backend.app.api.v1.auth.send_password_changed_email") as mock_changed:
        mock_changed.return_value = {"status": "ok"}
        res_reset = await client.post("/api/v1/auth/reset-password", json={
            "token": raw_token,
            "new_password": new_pass
        })
        assert res_reset.status_code == 200
        assert "успішно змінено" in res_reset.json()["message"]
        mock_changed.assert_called_once()

    # Verify old session token is now INVALID (session invalidation invariant)
    res_me_after = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access_token}"})
    assert res_me_after.status_code == 401

    # Verify token cannot be reused
    res_reuse = await client.post("/api/v1/auth/reset-password", json={
        "token": raw_token,
        "new_password": "AnotherPass2026!"
    })
    assert res_reuse.status_code == 400

    # Verify login with new password succeeds
    res_login = await client.post("/api/v1/auth/login", json={
        "login": user.login,
        "password": new_pass
    })
    assert res_login.status_code == 200
    assert "access_token" in res_login.json()


@pytest.mark.asyncio
async def test_change_password_triggers_email(client, db_session, superadmin_auth):
    clear_all_login_attempts()
    user = (await db_session.execute(select(User).where(User.login == settings.INITIAL_ADMIN_LOGIN.strip()))).scalars().first()
    user.email = "security_notice@maxi-ua.com"
    await db_session.commit()

    with patch("backend.app.api.v1.auth.send_password_changed_email") as mock_email:
        mock_email.return_value = {"status": "ok"}
        res = await client.post(
            "/api/v1/auth/change-password",
            headers=superadmin_auth,
            json={
                "current_password": settings.INITIAL_ADMIN_PASSWORD,
                "new_password": "NewChangedPassword2026!"
            }
        )
        assert res.status_code == 200
        mock_email.assert_called_once()
        assert mock_email.call_args[1]["to_addr"] == "security_notice@maxi-ua.com"


@pytest.mark.asyncio
async def test_admin_smtp_settings_masking_and_updating(client, superadmin_auth, db_session):
    # Set a real password in DB
    await update_system_settings(db_session, {
        "smtp_primary_password": "super_secret_gmail_pass",
        "smtp_fallback_password": "super_secret_ukrnet_pass"
    })

    # GET /settings must mask passwords with ********
    res_get = await client.get("/api/v1/system/settings", headers=superadmin_auth)
    assert res_get.status_code == 200
    data = res_get.json()
    assert data["settings"]["smtp_primary_password"] == "********"
    assert data["settings"]["smtp_fallback_password"] == "********"

    # PUT /settings with ******** must preserve the actual underlying passwords
    res_put = await client.put(
        "/api/v1/system/settings",
        headers=superadmin_auth,
        json={
            "smtp_primary_host": "smtp.gmail.com",
            "smtp_primary_password": "********",
            "smtp_fallback_password": "********"
        }
    )
    assert res_put.status_code == 200
    put_data = res_put.json()
    assert put_data["settings"]["smtp_primary_password"] == "********"

    # Verify actual password in DB was NOT changed to ********
    from backend.app.services.settings_service import get_runtime_setting
    assert get_runtime_setting("smtp_primary_password") == "super_secret_gmail_pass"
    assert get_runtime_setting("smtp_fallback_password") == "super_secret_ukrnet_pass"


@pytest.mark.asyncio
async def test_admin_email_test_endpoint(client, superadmin_auth):
    with patch("backend.app.services.email_service.send_email_with_failover") as mock_failover:
        mock_failover.return_value = {"status": "ok", "provider": "primary", "host": "smtp.gmail.com"}

        res = await client.post(
            "/api/v1/system/email/test",
            headers=superadmin_auth,
            json={"recipient": "test_admin@maxi-ua.com", "provider": "primary"}
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        mock_failover.assert_called_once()
        assert mock_failover.call_args[1]["force_provider"] == "primary"


@pytest.mark.asyncio
async def test_admin_weekly_digest_manual_send(client, superadmin_auth):
    with patch("backend.app.services.email_service.send_weekly_digest_email") as mock_digest:
        mock_digest.return_value = {"status": "ok", "provider": "primary"}

        res = await client.post(
            "/api/v1/system/email/weekly-digest/send?recipient=boss@maxi-ua.com",
            headers=superadmin_auth
        )
        assert res.status_code == 200
        assert "успішно надіслано" in res.json()["message"]
        mock_digest.assert_called_once()
        assert mock_digest.call_args[1]["recipients"] == ["boss@maxi-ua.com"]
        assert isinstance(mock_digest.call_args[1]["excel_bytes"], bytes)
