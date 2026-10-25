import json
import ssl
import smtplib
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import select

from backend.app.config import settings
from backend.app.models.user import User, Role
from backend.app.models.facility import Facility
from backend.app.models.generator import Generator
from backend.app.models.fuel import FuelStock
from backend.app.models.audit import AuditLog
from backend.app.services.audit_service import sanitize_historical_audit_logs, sanitize_audit_details
from backend.app.services.email_service import send_smtp_message_sync
from backend.app.services.settings_service import get_runtime_setting


# ============================================================================
# ПУНКТ 1 (P0): Усунення витоку паролів SMTP через журнал аудиту
# ============================================================================

@pytest.mark.asyncio
async def test_audit_sanitization_and_smtp_password_leak_prevention(client, superadmin_auth, db_session):
    """
    Перевіряє, що при збереженні паролів SMTP вони ніколи не потрапляють
    відкритим текстом у поле details_json таблиці audit_logs та не повертаються через API.
    """
    secret_primary = "MySuperSecretSmtpPass!999"
    secret_fallback = "FallbackSmtpSecretPass!888"

    # 1. Update settings with SMTP passwords
    update_res = await client.put(
        "/api/v1/system/settings",
        headers=superadmin_auth,
        json={
            "smtp_enabled": True,
            "smtp_primary_host": "smtp.gmail.com",
            "smtp_primary_password": secret_primary,
            "smtp_fallback_enabled": True,
            "smtp_fallback_host": "smtp.ukr.net",
            "smtp_fallback_password": secret_fallback
        }
    )
    assert update_res.status_code == 200

    # 2. Inspect raw DB AuditLog records directly
    raw_logs = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "SYSTEM_SETTINGS_UPDATED")
    )).scalars().all()
    assert len(raw_logs) >= 1
    last_log = raw_logs[-1]

    # Secrets MUST NOT appear anywhere in details_json
    assert secret_primary not in last_log.details_json
    assert secret_fallback not in last_log.details_json
    assert "[REDACTED]" in last_log.details_json

    # 3. Inspect audit logs API output (defense-in-depth egress check)
    api_audit_res = await client.get("/api/v1/audit?action=SYSTEM_SETTINGS_UPDATED", headers=superadmin_auth)
    assert api_audit_res.status_code == 200
    logs_data = api_audit_res.json()
    assert len(logs_data) >= 1
    for log_item in logs_data:
        if log_item.get("details_json"):
            assert secret_primary not in log_item["details_json"]
            assert secret_fallback not in log_item["details_json"]

    # 4. Test historical audit sanitization
    historical_log = AuditLog(
        user_id=1,
        action="LEGACY_AUDIT_LEAK",
        entity_type="SystemSetting",
        entity_id="global",
        details_json=json.dumps({"smtp_primary_password": "OldLeakedPassword123"}),
        ip_address="127.0.0.1"
    )
    db_session.add(historical_log)
    await db_session.commit()

    # Run sanitization routine
    cleaned_count = await sanitize_historical_audit_logs(db_session)
    assert cleaned_count >= 1

    # Verify legacy record was redacted
    await db_session.refresh(historical_log)
    assert "OldLeakedPassword123" not in historical_log.details_json
    assert "[REDACTED]" in historical_log.details_json


# ============================================================================
# ПУНКТ 2 (P0): Заборона передавання SMTP-облікових даних без TLS
# ============================================================================

def test_smtp_tls_fail_closed_when_starttls_unsupported():
    """
    Перевіряє fail-closed поведінку: якщо сервер не підтримує STARTTLS,
    викидається виняток, а login() ніколи не викликається.
    """
    mock_server = MagicMock()
    mock_server.has_extn.return_value = False  # STARTTLS is NOT supported

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        with pytest.raises(smtplib.SMTPNotSupportedError, match="не підтримує обов'язковий протокол шифрування STARTTLS"):
            send_smtp_message_sync(
                host="insecure.smtp.local",
                port=587,
                user="admin@local.host",
                password="PlaintextPasswordShouldNeverBeSent!",
                from_addr="admin@local.host",
                to_addr="dest@local.host",
                subject="Test",
                html_body="<p>Test</p>",
                use_ssl=False
            )

        # CRITICAL: login() MUST NOT be called!
        mock_server.login.assert_not_called()
        mock_server.send_message.assert_not_called()


def test_smtp_tls_fail_closed_when_starttls_handshake_fails():
    """
    Перевіряє, що при збої рукостискання STARTTLS або помилці сертифіката
    сесія негайно переривається, а передавання пароля блокується.
    """
    mock_server = MagicMock()
    mock_server.has_extn.return_value = True
    mock_server.starttls.side_effect = ssl.SSLError("Certificate verification failed or TLS error")

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        with pytest.raises(smtplib.SMTPException, match="Помилка встановлення захищеного з'єднання STARTTLS"):
            send_smtp_message_sync(
                host="smtp.gmail.com",
                port=587,
                user="admin@company.com",
                password="CriticalPassword123",
                from_addr="admin@company.com",
                to_addr="dest@company.com",
                subject="Test",
                html_body="<p>Test</p>",
                use_ssl=False
            )

        # CRITICAL: login() MUST NOT be called!
        mock_server.login.assert_not_called()
        mock_server.send_message.assert_not_called()


def test_smtp_tls_success_allows_authenticated_send():
    """
    Перевіряє, що при успішному переході на STARTTLS аутентифікація дозволяється.
    """
    mock_server = MagicMock()
    mock_server.has_extn.return_value = True
    mock_server.starttls.return_value = (220, b"2.0.0 Ready to start TLS")

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        send_smtp_message_sync(
            host="smtp.gmail.com",
            port=587,
            user="admin@company.com",
            password="ValidAppPassword",
            from_addr="admin@company.com",
            to_addr="dest@company.com",
            subject="Test",
            html_body="<p>Test</p>",
            use_ssl=False
        )

        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("admin@company.com", "ValidAppPassword")
        mock_server.send_message.assert_called_once()


def test_smtp_ssl_mode_uses_secure_ssl_client():
    """
    Перевіряє, що при виборі режиму SSL використовується SMTP_SSL із валідацією сертифіката.
    """
    mock_server = MagicMock()

    with patch("smtplib.SMTP_SSL") as mock_ssl_cls:
        mock_ssl_cls.return_value.__enter__.return_value = mock_server

        send_smtp_message_sync(
            host="smtp.ukr.net",
            port=465,
            user="user@ukr.net",
            password="AppPassword465",
            from_addr="user@ukr.net",
            to_addr="dest@ukr.net",
            subject="Test",
            html_body="<p>Test</p>",
            use_ssl=True
        )

        mock_ssl_cls.assert_called_once()
        mock_server.login.assert_called_once_with("user@ukr.net", "AppPassword465")
        mock_server.send_message.assert_called_once()


# ============================================================================
# ПУНКТ 3 (P1): Усунення обходу ізоляції між об’єктами
# ============================================================================

@pytest.mark.asyncio
async def test_facility_isolation_unassigned_user_lockdown(client, superadmin_auth, db_session):
    """
    Перевіряє суворе правило Fail-Closed для користувача без закріпленого facility_id:
    - перелік об'єктів повертає [];
    - запити до конкретного об'єкта або генератора повертають 403 з поясненням.
    """
    # 1. Create an operator explicitly unassigned (facility_id=None)
    from backend.app.core.security import get_password_hash
    op_unassigned = User(
        login="unassigned_op",
        email="unassigned@test.ua",
        full_name="Оператор Без Об'єкта",
        password_hash=get_password_hash("SecretPass123!"),
        facility_id=None,
        is_active=True,
        is_superadmin=False
    )
    # Assign operator role (role_id=3)
    op_role = await db_session.get(Role, 3)
    if op_role:
        op_unassigned.roles = [op_role]
    db_session.add(op_unassigned)
    await db_session.commit()

    # 2. Log in as unassigned operator
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"login": "unassigned_op", "password": "SecretPass123!"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    unassigned_auth = {"Authorization": f"Bearer {token}"}

    # 3. Verify GET /api/v1/facilities returns empty list
    fac_list_res = await client.get("/api/v1/facilities", headers=unassigned_auth)
    assert fac_list_res.status_code == 200
    assert fac_list_res.json() == []

    # 4. Accessing facility #1 directly returns 403 Forbidden
    fac_res = await client.get("/api/v1/facilities/1", headers=unassigned_auth)
    assert fac_res.status_code == 403
    assert "очікує закріплення за об'єктом адміністратором" in fac_res.json()["detail"]

    # 5. Accessing generator returns 403 Forbidden
    gen_res = await client.get("/api/v1/generator", headers=unassigned_auth)
    assert gen_res.status_code == 403
    assert "очікує закріплення за об'єктом адміністратором" in gen_res.json()["detail"]

    # 6. Accessing fuel stock returns 403 Forbidden
    fuel_res = await client.get("/api/v1/fuel/stock", headers=unassigned_auth)
    assert fuel_res.status_code == 403


@pytest.mark.asyncio
async def test_cross_facility_fuel_transfer_rejection(client, superadmin_auth):
    """
    Перевіряє заборону переливу палива між складом одного об'єкта та генератором іншого об'єкта.
    """
    # Create Facility 2 with generator and fuel stock
    fac2_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={"name": "Філія для перевірки переливу", "address": "вул. Тестова 99"}
    )
    assert fac2_res.status_code == 201
    fac2_id = fac2_res.json()["id"]

    # Create Generator on Facility 2
    gen2_res = await client.post(
        "/api/v1/generator",
        headers=superadmin_auth,
        json={
            "facility_id": fac2_id,
            "name": "Генератор Філії 2",
            "model": "Matari",
            "manufacturer": "Matari Inc",
            "serial_number": "SN-MATARI-99",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0
        }
    )
    assert gen2_res.status_code == 201
    gen2_id = gen2_res.json()["id"]

    # Get Fuel Stock for Facility 1 (default stock)
    stock1_res = await client.get("/api/v1/fuel/stock?facility_id=1", headers=superadmin_auth)
    assert stock1_res.status_code == 200
    stock1_id = stock1_res.json()["id"]

    # Attempt cross-facility transfer: Stock from Facility 1 -> Generator on Facility 2
    bad_transfer = await client.post(
        "/api/v1/fuel/transfer",
        headers=superadmin_auth,
        json={
            "facility_id": fac2_id,
            "stock_id": stock1_id,
            "generator_id": gen2_id,
            "liters": 5.0
        }
    )
    assert bad_transfer.status_code == 400
    assert "належать до різних об'єктів" in bad_transfer.json()["detail"]


# ============================================================================
# ПУНКТ 4 (P1): Обмеження видалення об’єкта виключно SuperAdmin
# ============================================================================

@pytest.mark.asyncio
async def test_facility_deletion_restricted_exclusively_to_superadmin(client, superadmin_auth, operator_auth, db_session):
    """
    Перевіряє, що видалення об'єкта дозволено виключно SuperAdmin,
    а звичайні адміністратори та оператори отримують 403 Forbidden.
    Також перевіряє аудит видалення.
    """
    # 1. Create a dummy facility to delete
    fac_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={"name": "Об'єкт під видалення", "address": "вул. Каскадна, 1"}
    )
    assert fac_res.status_code == 201
    fac_id = fac_res.json()["id"]

    # 2. Create regular admin user (not superadmin)
    from backend.app.core.security import get_password_hash
    admin_user = User(
        login="regular_admin",
        email="admin@test.ua",
        full_name="Звичайний Адміністратор",
        password_hash=get_password_hash("AdminPass123!"),
        facility_id=1,
        is_active=True,
        is_superadmin=False
    )
    admin_role = await db_session.get(Role, 2)  # Role 2 is admin
    if admin_role:
        admin_user.roles = [admin_role]
    db_session.add(admin_user)
    await db_session.commit()

    admin_login = await client.post(
        "/api/v1/auth/login",
        json={"login": "regular_admin", "password": "AdminPass123!"}
    )
    assert admin_login.status_code == 200
    admin_auth = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    # 3. Operator tries to delete -> 403 Forbidden
    del_by_op = await client.delete(f"/api/v1/facilities/{fac_id}", headers=operator_auth)
    assert del_by_op.status_code == 403

    # 4. Regular Admin tries to delete -> 403 Forbidden
    del_by_admin = await client.delete(f"/api/v1/facilities/{fac_id}", headers=admin_auth)
    assert del_by_admin.status_code == 403
    assert "виключно головному системному адміністратору" in del_by_admin.json()["detail"]

    # 5. SuperAdmin deletes -> 200 OK
    del_by_super = await client.delete(f"/api/v1/facilities/{fac_id}?cascade=true", headers=superadmin_auth)
    assert del_by_super.status_code == 200
    assert "успішно видалено" in del_by_super.json()["message"]

    # 6. Audit check
    del_audit = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "FACILITY_DELETED", AuditLog.entity_id == str(fac_id))
    )).scalars().first()
    assert del_audit is not None
    details = json.loads(del_audit.details_json)
    assert details["name"] == "Об'єкт під видалення"
    assert "fuel_stocks_deleted" in details


# ============================================================================
# ПУНКТ 5 (P1): Серверна валідація системних налаштувань за замовчуванням
# ============================================================================

@pytest.mark.asyncio
async def test_system_settings_server_validation_domain_integrity(client, superadmin_auth, db_session):
    """
    Перевіряє серверну валідацію системних налаштувань:
    - неіснуючі ID відхиляються з кодом 400;
    - розсинхронізація об'єкта, генератора та складу відхиляється;
    - налаштування залишаються атомарно незмінними при помилці.
    """
    # 1. Non-existent facility ID
    res1 = await client.put(
        "/api/v1/system/settings",
        headers=superadmin_auth,
        json={"default_facility_id": 99999}
    )
    assert res1.status_code == 400
    assert "не знайдено в системі" in res1.json()["detail"]

    # 2. Non-existent generator ID
    res2 = await client.put(
        "/api/v1/system/settings",
        headers=superadmin_auth,
        json={"default_generator_id": 99999}
    )
    assert res2.status_code == 400
    assert "не знайдено в системі" in res2.json()["detail"]

    # 3. Non-existent fuel stock ID
    res3 = await client.put(
        "/api/v1/system/settings",
        headers=superadmin_auth,
        json={"default_fuel_stock_id": 99999}
    )
    assert res3.status_code == 400
    assert "не знайдено в системі" in res3.json()["detail"]

    # 4. Create second facility with its own generator
    fac2_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={"name": "Філія для валідації налаштувань", "address": "вул. Валідаційна 1"}
    )
    assert fac2_res.status_code == 201
    fac2_id = fac2_res.json()["id"]

    gen2_res = await client.post(
        "/api/v1/generator",
        headers=superadmin_auth,
        json={
            "facility_id": fac2_id,
            "name": "Генератор Філії №2",
            "model": "Kipor",
            "manufacturer": "Kipor Power",
            "serial_number": "SN-KIP-102",
            "rated_power_kw": 4.0,
            "tank_capacity_l": 20.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 1.8
        }
    )
    assert gen2_res.status_code == 201
    gen2_id = gen2_res.json()["id"]

    # 5. Mismatched binding: default_facility_id = 1, but default_generator_id is from facility 2
    res_mismatch = await client.put(
        "/api/v1/system/settings",
        headers=superadmin_auth,
        json={
            "default_facility_id": 1,
            "default_generator_id": gen2_id
        }
    )
    assert res_mismatch.status_code == 400
    assert "закріплений за об'єктом ID" in res_mismatch.json()["detail"]

    # 6. Verify atomic state: default settings in runtime were NOT mutated
    assert get_runtime_setting("default_generator_id") != gen2_id

    # 7. Valid binding: default_facility_id = fac2_id with generator from fac2_id
    res_valid = await client.put(
        "/api/v1/system/settings",
        headers=superadmin_auth,
        json={
            "default_facility_id": fac2_id,
            "default_generator_id": gen2_id
        }
    )
    assert res_valid.status_code == 200
    assert get_runtime_setting("default_facility_id") == fac2_id
    assert get_runtime_setting("default_generator_id") == gen2_id
