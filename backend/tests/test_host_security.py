import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.config import settings


@pytest.mark.asyncio
async def test_trusted_host_blocks_unauthorized_domains():
    transport = ASGITransport(app=app)

    # 1. Test clone domain tanvuongphat.com -> must be blocked with 400 Bad Request
    async with AsyncClient(transport=transport, base_url="https://tanvuongphat.com") as client:
        res = await client.get("/api/health")
        assert res.status_code == 400
        assert "Invalid host header" in res.text

    # 2. Test another rogue/phishing domain -> must be blocked
    async with AsyncClient(transport=transport, base_url="https://fake-generator.xyz") as client:
        res = await client.get("/api/health")
        assert res.status_code == 400
        assert "Invalid host header" in res.text

    # 3. Test configured PRIMARY_DOMAIN -> must be allowed and return domain in health
    async with AsyncClient(transport=transport, base_url=f"https://{settings.PRIMARY_DOMAIN}") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["primary_domain"] == settings.PRIMARY_DOMAIN

    # 4. Test localhost -> must be allowed
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200

    # 5. Test index HTML injection of dynamic primary domain
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        res = await client.get("/")
        if res.status_code == 200 and "text/html" in res.headers.get("content-type", ""):
            assert f'<meta name="app-primary-domain" content="{settings.PRIMARY_DOMAIN}">' in res.text


def test_effective_allowed_hosts_and_cors_property():
    # Verify dynamic host list includes primary domain and essential defaults
    hosts = settings.effective_allowed_hosts
    assert settings.PRIMARY_DOMAIN in hosts
    assert f"www.{settings.PRIMARY_DOMAIN}" in hosts
    assert "localhost" in hosts
    assert "127.0.0.1" in hosts
    assert "test" in hosts

    # Verify dynamic CORS origins
    cors = settings.effective_cors_origins
    assert f"https://{settings.PRIMARY_DOMAIN}" in cors
    assert "http://localhost:8000" in cors
