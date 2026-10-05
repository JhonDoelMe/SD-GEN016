import pytest


@pytest.mark.asyncio
async def test_initial_superadmin_login(client):
    res = await client.post(
        "/api/v1/auth/login",
        json={"login": "superadmin", "password": "SuperAdminPass123!"}
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["login"] == "superadmin"
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
