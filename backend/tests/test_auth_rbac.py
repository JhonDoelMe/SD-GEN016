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

