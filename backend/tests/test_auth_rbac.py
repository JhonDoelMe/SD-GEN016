import pytest
from backend.app.config import settings


@pytest.mark.asyncio
async def test_initial_superadmin_login(client):
    res = await client.post(
        "/api/v1/auth/login",
        json={
            "login": settings.INITIAL_ADMIN_LOGIN.strip(),
            "password": settings.INITIAL_ADMIN_PASSWORD
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["login"] == settings.INITIAL_ADMIN_LOGIN.strip()
    assert data["user"]["is_superadmin"] is True
    assert "generator:start" in data["user"]["permissions"]
    assert "system:adjust" in data["user"]["permissions"]


@pytest.mark.asyncio
async def test_invalid_login_credentials(client):
    res = await client.post(
        "/api/v1/auth/login",
        json={"login": "superadmin", "password": "WrongPassword"}
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_blocked_user_cannot_login(client, superadmin_auth):
    # Create user
    res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={"login": "tempuser", "password": "Pass12345!", "full_name": "Тест Блок"}
    )
    assert res.status_code == 201
    user_id = res.json()["id"]

    # Block user
    update_res = await client.put(
        f"/api/v1/users/{user_id}",
        headers=superadmin_auth,
        json={"is_active": False}
    )
    assert update_res.status_code == 200
    assert update_res.json()["is_active"] is False

    # Attempt login
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"login": "tempuser", "password": "Pass12345!"}
    )
    assert login_res.status_code == 403
    assert "заблокований" in login_res.json()["detail"]


@pytest.mark.asyncio
async def test_rbac_viewer_cannot_start_generator(client, viewer_auth):
    # Viewer tries to start generator
    res = await client.post(
        "/api/v1/generator/start",
        headers=viewer_auth,
        json={}
    )
    # Must be forbidden 403
    assert res.status_code == 403
    assert "Недостатньо прав" in res.json()["detail"]


@pytest.mark.asyncio
async def test_remember_me_login_and_cookie_auth(client):
    # Test login with remember_me=True
    res = await client.post(
        "/api/v1/auth/login",
        json={
            "login": settings.INITIAL_ADMIN_LOGIN.strip(),
            "password": settings.INITIAL_ADMIN_PASSWORD,
            "remember_me": True
        }
    )
    assert res.status_code == 200
    assert "access_token" in res.cookies
    cookie_header = res.headers.get("set-cookie", "")
    assert "Max-Age=5184000" in cookie_header or "max-age=5184000" in cookie_header.lower()

    # Authenticate via cookie directly (without Authorization header)
    me_res = await client.get("/api/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["login"] == settings.INITIAL_ADMIN_LOGIN.strip()

    # Logout clears cookie
    logout_res = await client.post("/api/v1/auth/logout")
    assert logout_res.status_code == 200


@pytest.mark.asyncio
async def test_brute_force_rate_limit_lockout(client):
    # Exceed LOGIN_MAX_ATTEMPTS (5)
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        res = await client.post(
            "/api/v1/auth/login",
            json={"login": "superadmin", "password": "WrongPassword123"}
        )
        assert res.status_code == 401

    # 6th attempt must be blocked with 429 Too Many Requests even with valid password
    locked_res = await client.post(
        "/api/v1/auth/login",
        json={
            "login": settings.INITIAL_ADMIN_LOGIN.strip(),
            "password": settings.INITIAL_ADMIN_PASSWORD
        }
    )
    assert locked_res.status_code == 429
    assert "Retry-After" in locked_res.headers


@pytest.mark.asyncio
async def test_server_side_login_and_password_validation(client, superadmin_auth):
    # Invalid login characters (SQL injection / XSS attempt in login)
    bad_login_res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "admin' OR '1'='1",
            "password": "ValidPassword123!",
            "full_name": "Тестовий Користувач"
        }
    )
    assert bad_login_res.status_code == 422

    # Weak password (too short or no digits)
    weak_pass_res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "valid_user1",
            "password": "onlyletters",
            "full_name": "Тестовий Користувач"
        }
    )
    assert weak_pass_res.status_code == 422

    # XSS in full_name rejected
    xss_name_res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "valid_user2",
            "password": "ValidPassword123!",
            "full_name": "<script>alert(1)</script>"
        }
    )
    assert xss_name_res.status_code == 422


@pytest.mark.asyncio
async def test_facility_modification_requires_permission(client, viewer_auth, operator_auth):
    # Viewer cannot create or delete facilities
    create_res = await client.post(
        "/api/v1/facilities",
        headers=viewer_auth,
        json={"name": "Unauthorized Facility"}
    )
    assert create_res.status_code == 403

    # Operator without generator:configure cannot delete facility
    del_res = await client.delete("/api/v1/facilities/1", headers=operator_auth)
    assert del_res.status_code == 403


@pytest.mark.asyncio
async def test_security_headers_and_minimal_health(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "app_env" not in data
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in res.headers




@pytest.mark.asyncio
async def test_admin_cannot_clean_db_or_reset(client, admin_auth, superadmin_auth):
    # Admin tries to call system reset
    admin_res = await client.post(
        "/api/v1/system/reset",
        headers=admin_auth,
        json={
            "mode": "reports_clean",
            "admin_password": "AdminPass123!",
            "confirm_code": "RESET"
        }
    )
    assert admin_res.status_code == 403
    assert "головному системному адміністратору" in admin_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_cannot_perform_system_adjustments(client, admin_auth):
    # Admin tries to call system adjustment
    admin_res = await client.post(
        "/api/v1/adjustments",
        headers=admin_auth,
        json={
            "facility_id": 1,
            "generator_id": 1,
            "adjustment_type": "HOURS",
            "delta_value": 5.0,
            "reason": "Test"
        }
    )
    assert admin_res.status_code == 403


@pytest.mark.asyncio
async def test_operator_strict_rbac_matrix(client, operator_auth, superadmin_auth):
    # 1. Setup default generator if needed
    await client.get("/api/v1/generator", headers=operator_auth)

    # 2. Operator CANNOT manage facilities
    fac_res = await client.post("/api/v1/facilities", headers=operator_auth, json={"name": "Новий об'єкт"})
    assert fac_res.status_code == 403

    # 3. Operator CANNOT create/edit/delete fuel stocks
    stock_res = await client.post("/api/v1/fuel/stock/new", headers=operator_auth, json={"name": "Склад", "fuel_type": "А-95"})
    assert stock_res.status_code == 403

    # 4. Operator CANNOT recalculate maintenance schedule or do SCHEDULED maintenance
    recalc_res = await client.post("/api/v1/maintenance/schedule/recalculate", headers=operator_auth)
    assert recalc_res.status_code == 403

    maint_sched_res = await client.post(
        "/api/v1/maintenance/record",
        headers=operator_auth,
        json={
            "maintenance_type": "SCHEDULED",
            "operating_hours": 10.0,
            "work_description": "Регламент"
        }
    )
    assert maint_sched_res.status_code == 403

    # Operator CAN do INTERMEDIATE maintenance
    maint_inter_res = await client.post(
        "/api/v1/maintenance/record",
        headers=operator_auth,
        json={
            "maintenance_type": "INTERMEDIATE",
            "operating_hours": 10.0,
            "work_description": "Заміна масла"
        }
    )
    assert maint_inter_res.status_code == 201

    # 5. Operator CANNOT view Audit, Reports, Users or Settings
    audit_res = await client.get("/api/v1/audit", headers=operator_auth)
    assert audit_res.status_code == 403

    rep_res = await client.get("/api/v1/reports/summary", headers=operator_auth)
    assert rep_res.status_code == 403

    users_res = await client.get("/api/v1/users", headers=operator_auth)
    assert users_res.status_code == 403

    settings_res = await client.get("/api/v1/system/settings", headers=operator_auth)
    assert settings_res.status_code == 403


@pytest.mark.asyncio
async def test_viewer_strictly_dashboard_only(client, viewer_auth):
    # Viewer CAN view generator status on dashboard
    gen_res = await client.get("/api/v1/generator", headers=viewer_auth)
    assert gen_res.status_code == 200

    # Viewer CANNOT start/stop/manual-run generator
    assert (await client.post("/api/v1/generator/start", headers=viewer_auth, json={})).status_code == 403
    assert (await client.post("/api/v1/generator/stop", headers=viewer_auth, json={})).status_code == 403
    assert (await client.post("/api/v1/generator/manual-run", headers=viewer_auth, json={
        "start_time": "2026-10-20T08:00:00Z",
        "end_time": "2026-10-20T10:00:00Z"
    })).status_code == 403

    # Viewer CANNOT access fuel balances, receipts, transfers
    assert (await client.get("/api/v1/fuel/stocks", headers=viewer_auth)).status_code == 403
    assert (await client.get("/api/v1/fuel/summary", headers=viewer_auth)).status_code == 403
    assert (await client.post("/api/v1/fuel/receipt", headers=viewer_auth, json={
        "fuel_type": "А-95", "liters": 10.0, "cost_total": 500.0, "price_per_liter": 50.0
    })).status_code == 403

    # Viewer CANNOT record maintenance or view maintenance schedule
    assert (await client.get("/api/v1/maintenance/schedule", headers=viewer_auth)).status_code == 403
    assert (await client.post("/api/v1/maintenance/record", headers=viewer_auth, json={
        "maintenance_type": "INTERMEDIATE", "operating_hours": 10.0, "work_description": "Тест"
    })).status_code == 403

    # Viewer CANNOT report faults or view faults tab
    assert (await client.get("/api/v1/faults", headers=viewer_auth)).status_code == 403
    assert (await client.post("/api/v1/faults", headers=viewer_auth, json={
        "generator_id": 1, "title": "Дефект", "description": "Опис", "priority": "LOW"
    })).status_code == 403

    # Viewer CANNOT access notifications settings
    assert (await client.get("/api/v1/notifications/settings", headers=viewer_auth)).status_code == 403



@pytest.mark.asyncio
async def test_superadmin_full_user_crud_and_protections(client, superadmin_auth, admin_auth):
    # 1. SuperAdmin creates a user
    create_res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "test_operator_crud",
            "password": "Password123!",
            "full_name": "Тестовий Оператор КРУД",
            "email": "testop@example.com",
            "role_ids": [3]
        }
    )
    assert create_res.status_code == 201
    user_id = create_res.json()["id"]

    # 2. SuperAdmin updates user (login, full_name, email, role, status)
    update_res = await client.put(
        f"/api/v1/users/{user_id}",
        headers=superadmin_auth,
        json={
            "login": "test_operator_renamed",
            "full_name": "Перейменований Оператор",
            "email": "updated@example.com",
            "role_ids": [4],  # switch to viewer
            "is_active": True
        }
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["login"] == "test_operator_renamed"
    assert updated_data["full_name"] == "Перейменований Оператор"
    assert updated_data["email"] == "updated@example.com"
    assert any(r["name"] == "viewer" for r in updated_data["roles"])

    # 3. SuperAdmin resets password
    reset_res = await client.post(
        f"/api/v1/users/{user_id}/reset-password",
        headers=superadmin_auth,
        json={"new_password": "NewSecretPass456!"}
    )
    assert reset_res.status_code == 200

    # Verify login with new credentials
    login_new = await client.post(
        "/api/v1/auth/login",
        json={"login": "test_operator_renamed", "password": "NewSecretPass456!"}
    )
    assert login_new.status_code == 200

    # 4. SuperAdmin deletes user
    del_res = await client.delete(
        f"/api/v1/users/{user_id}",
        headers=superadmin_auth
    )
    assert del_res.status_code == 200

    # 5. Admin CANNOT create, edit, reset password, or delete user
    assert (await client.post(
        "/api/v1/users",
        headers=admin_auth,
        json={"login": "admin_fail", "password": "Password123!", "full_name": "Fail"}
    )).status_code == 403

    # Admin CAN view users
    assert (await client.get("/api/v1/users", headers=admin_auth)).status_code == 200

    # 6. Protections: SuperAdmin CANNOT be modified, blocked, or deleted
    users_list = (await client.get("/api/v1/users", headers=superadmin_auth)).json()
    superadmin_user = next(u for u in users_list if u["is_superadmin"])
    super_id = superadmin_user["id"]

    # Attempt to edit superadmin
    edit_super_res = await client.put(
        f"/api/v1/users/{super_id}",
        headers=superadmin_auth,
        json={"full_name": "Зломити Суперадміна"}
    )
    assert edit_super_res.status_code == 400

    # Attempt to reset password of superadmin via user endpoint
    reset_super_res = await client.post(
        f"/api/v1/users/{super_id}/reset-password",
        headers=superadmin_auth,
        json={"new_password": "HackedPass123!"}
    )
    assert reset_super_res.status_code == 400

    # Attempt to delete superadmin
    del_super_res = await client.delete(
        f"/api/v1/users/{super_id}",
        headers=superadmin_auth
    )
    assert del_super_res.status_code == 400
