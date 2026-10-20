import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app


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

    # 3. Test official domain generator-016.pp.ua -> must be allowed
    async with AsyncClient(transport=transport, base_url="https://generator-016.pp.ua") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"

    # 4. Test localhost -> must be allowed
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
