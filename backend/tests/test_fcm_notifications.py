import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.notification import PushSubscription
from backend.app.services import fcm_service
from backend.app.services.notification_service import send_push_notification


def _ephemeral_service_account_json() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return json.dumps({
        "type": "service_account",
        "project_id": "sdgen-test-project",
        "private_key": pem,
        "client_email": "fcm-sender@sdgen-test-project.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    })


@pytest.mark.asyncio
async def test_fcm_subscribe_unsubscribe_and_status(
    client: AsyncClient,
    superadmin_auth: dict,
    db_session: AsyncSession,
):
    status_res = await client.get("/api/v1/notifications/fcm/status", headers=superadmin_auth)
    assert status_res.status_code == 200
    assert "configured" in status_res.json()

    invalid_res = await client.post(
        "/api/v1/notifications/fcm/subscribe",
        json={"token": "too-short"},
        headers=superadmin_auth,
    )
    assert invalid_res.status_code == 422

    fake_token = "fcm_test_device_token_0123456789abcdef"
    sub_res = await client.post(
        "/api/v1/notifications/fcm/subscribe",
        json={"token": fake_token, "facility_id": 1},
        headers=superadmin_auth,
    )
    assert sub_res.status_code == 200
    data = sub_res.json()
    assert data["endpoint"] == f"fcm://{fake_token}"
    assert data["is_active"] is True

    db_row = (
        await db_session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == f"fcm://{fake_token}")
        )
    ).scalars().first()
    assert db_row is not None
    assert db_row.is_active is True

    unsub_res = await client.post(
        "/api/v1/notifications/fcm/unsubscribe",
        json={"token": fake_token},
        headers=superadmin_auth,
    )
    assert unsub_res.status_code == 200
    assert unsub_res.json()["success"] is True

    await db_session.refresh(db_row)
    assert db_row.is_active is False


@pytest.mark.asyncio
async def test_send_push_routes_fcm_and_deactivates_unregistered(
    client: AsyncClient,
    superadmin_auth: dict,
    db_session: AsyncSession,
):
    ok_token = "fcm_valid_device_token_0123456789abcdef"
    dead_token = "fcm_dead_device_token_0123456789abcdef"

    for tok in (ok_token, dead_token):
        res = await client.post(
            "/api/v1/notifications/fcm/subscribe",
            json={"token": tok, "facility_id": 1},
            headers=superadmin_auth,
        )
        assert res.status_code == 200

    fcm_service.reset_fcm_token_cache()
    sa_json = _ephemeral_service_account_json()
    sent_payloads = []

    async def fake_post(url, **kwargs):
        mock_resp = MagicMock()
        if "oauth2.googleapis.com/token" in url:
            mock_resp.status_code = 200
            mock_resp.raise_for_status = lambda: None
            mock_resp.json = lambda: {"access_token": "oauth-access-token-123", "expires_in": 3600}
            return mock_resp

        body = kwargs.get("json") or {}
        sent_payloads.append(body)
        target = body["message"]["token"]
        if target == dead_token:
            mock_resp.status_code = 404
            mock_resp.text = '{"error":{"status":"NOT_FOUND","details":[{"errorCode":"UNREGISTERED"}]}}'
        else:
            mock_resp.status_code = 200
            mock_resp.text = '{"name":"projects/sdgen-test-project/messages/1"}'
        return mock_resp

    try:
        with (
            patch.object(fcm_service.settings, "FIREBASE_SERVICE_ACCOUNT_JSON", sa_json),
            patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)),
        ):
            result = await send_push_notification(
                db=db_session,
                title="Повітряна тривога",
                body="Самар — оголошено тривогу",
                event_type="AIR_ALERT_START",
                facility_id=1,
            )
    finally:
        fcm_service.reset_fcm_token_cache()

    assert result["sent"] == 1
    assert result["failed"] == 1
    assert len(sent_payloads) == 2
    assert all(p["message"]["android"]["priority"] == "HIGH" for p in sent_payloads)
    assert all(p["message"]["android"]["notification"]["channel_id"] == "sdgen_alerts" for p in sent_payloads)

    dead_row = (
        await db_session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == f"fcm://{dead_token}")
        )
    ).scalars().first()
    ok_row = (
        await db_session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == f"fcm://{ok_token}")
        )
    ).scalars().first()
    assert dead_row.is_active is False
    assert ok_row.is_active is True
