import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.services.init_service import seed_initial_data
from backend.app.models.user import User, Role
from backend.app.core.security import get_password_hash

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        await seed_initial_data(session)
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def superadmin_auth(client):
    # Log in as initial superadmin
    res = await client.post(
        "/api/v1/auth/login",
        json={"login": "superadmin", "password": "SuperAdminPass123!"}
    )
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="function")
async def operator_auth(client, db_session, superadmin_auth):
    # Create operator user via users API or direct DB
    res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "operator1",
            "password": "OperatorPass123!",
            "full_name": "Іван Оператор",
            "role_ids": [3]  # operator role
        }
    )
    assert res.status_code == 201, res.text

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"login": "operator1", "password": "OperatorPass123!"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="function")
async def viewer_auth(client, superadmin_auth):
    # Create viewer user
    res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "viewer1",
            "password": "ViewerPass123!",
            "full_name": "Ольга Спостерігач",
            "role_ids": [4]  # viewer role
        }
    )
    assert res.status_code == 201, res.text

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"login": "viewer1", "password": "ViewerPass123!"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
