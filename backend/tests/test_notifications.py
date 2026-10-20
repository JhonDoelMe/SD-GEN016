import pytest
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.notification import PushSubscription, NotificationLog
from backend.app.models.generator import Generator
from backend.app.services.notification_service import send_push_notification, check_and_notify_maintenance_due


@pytest.mark.asyncio
async def test_get_vapid_public_key(client: AsyncClient, superadmin_auth: dict):
    res = await client.get("/api/v1/notifications/vapid-public-key", headers=superadmin_auth)
    assert res.status_code == 200
    data = res.json()
    assert "public_key" in data
    assert len(data["public_key"]) > 30


@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe_push(client: AsyncClient, superadmin_auth: dict, db_session: AsyncSession):
    sub_payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-token-12345",
        "keys": {
            "p256dh": "BFdHB8a7vG8vNjOXCXHJ0cz0Diwh2fGJ42wpnMS5YWwdZlOMGaKEhiW1Gm8BeTBnE8xC9SoAkRlyD55ynQ_0pPE",
            "auth": "MDEyMzQ1Njc4OWFiY2RlZg"
        },
        "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) TestBrowser",
        "facility_id": 1
    }

    res_sub = await client.post("/api/v1/notifications/subscribe", json=sub_payload, headers=superadmin_auth)
    assert res_sub.status_code == 200
    sub_data = res_sub.json()
    assert sub_data["endpoint"] == sub_payload["endpoint"]
    assert sub_data["is_active"] is True

    # Verify stored in DB
    db_res = await db_session.execute(select(PushSubscription).where(PushSubscription.endpoint == sub_payload["endpoint"]))
    db_sub = db_res.scalars().first()
    assert db_sub is not None
    assert db_sub.is_active is True

    # Unsubscribe
    res_unsub = await client.post(
        "/api/v1/notifications/unsubscribe",
        json={"endpoint": sub_payload["endpoint"]},
        headers=superadmin_auth
    )
    assert res_unsub.status_code == 200
    assert res_unsub.json()["success"] is True

    # Verify deactivated
    await db_session.refresh(db_sub)
    assert db_sub.is_active is False


@pytest.mark.asyncio
async def test_notification_settings_access_and_update(
    client: AsyncClient,
    superadmin_auth: dict,
    operator_auth: dict,
    viewer_auth: dict
):
    # 1. Retrieve current settings
    res = await client.get("/api/v1/notifications/settings", headers=superadmin_auth)
    assert res.status_code == 200
    settings_data = res.json()
    assert "notifications_enabled" in settings_data
    assert "vapid_public_key" in settings_data
    assert settings_data["max_maintenance_notifications_per_day"] == 2

    # 2. Viewer attempt to update settings -> forbidden (403)
    update_payload = {
        "notifications_enabled": True,
        "notify_generator_start": True,
        "notify_generator_stop": True,
        "notify_low_fuel": True,
        "low_fuel_threshold_l": 6.5,
        "notify_maintenance": True,
        "max_maintenance_notifications_per_day": 2,
        "notify_critical_faults": True
    }
    res_viewer = await client.put("/api/v1/notifications/settings", json=update_payload, headers=viewer_auth)
    assert res_viewer.status_code == 403

    # 3. Operator can update notification settings per business rules (200)
    res_op = await client.put("/api/v1/notifications/settings", json=update_payload, headers=operator_auth)
    assert res_op.status_code == 200
    updated_op = res_op.json()
    assert updated_op["low_fuel_threshold_l"] == 6.5

    # 4. SuperAdmin update settings -> success
    res_admin = await client.put("/api/v1/notifications/settings", json=update_payload, headers=superadmin_auth)
    assert res_admin.status_code == 200
    updated = res_admin.json()
    assert updated["low_fuel_threshold_l"] == 6.5
    assert updated["max_maintenance_notifications_per_day"] == 2


@pytest.mark.asyncio
async def test_send_test_notification_and_logs(client: AsyncClient, superadmin_auth: dict):
    test_payload = {
        "title": "Тест системи",
        "body": "Перевірка доставки сповіщення"
    }
    res = await client.post("/api/v1/notifications/test", json=test_payload, headers=superadmin_auth)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    # Retrieve logs
    res_logs = await client.get("/api/v1/notifications/logs?limit=10", headers=superadmin_auth)
    assert res_logs.status_code == 200
    logs = res_logs.json()
    assert len(logs) > 0
    assert logs[0]["event_type"] == "TEST"
    assert logs[0]["title"] == "Тест системи"


@pytest.mark.asyncio
async def test_maintenance_rate_limiting_max_2_per_day(db_session: AsyncSession):
    """Verify strict rule: no more than 2 maintenance notifications per generator per day."""
    # Ensure generator exists
    gen_res = await db_session.execute(select(Generator))
    generator = gen_res.scalars().first()
    if not generator:
        generator = Generator(
            name="Тестовий Генератор",
            model="G-5000",
            manufacturer="Honda",
            serial_number="SN-TEST-NOTIF",
            is_configured=True
        )
        db_session.add(generator)
        await db_session.commit()
        await db_session.refresh(generator)

    # 1. First maintenance notification of the day -> allowed
    res1 = await send_push_notification(
        db=db_session,
        title="ТО 1",
        body="Нагадування 1",
        event_type="MAINTENANCE_DUE",
        generator_id=generator.id
    )
    assert res1.get("skipped") is not True

    # 2. Emulate 2nd notification with timestamp within today's calendar range
    import datetime
    from backend.app.core.timezone import now_facility
    fac_now = now_facility()
    today_start_fac = fac_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_fac.astimezone(datetime.timezone.utc).replace(tzinfo=None)

    log2 = NotificationLog(
        event_type="MAINTENANCE_DUE",
        generator_id=generator.id,
        title="ТО 2",
        body="Нагадування 2",
        recipients_count=0,
        success_count=0,
        failure_count=0,
        created_at=today_start_utc + datetime.timedelta(seconds=60)
    )
    db_session.add(log2)
    await db_session.commit()

    # 3. Third maintenance notification today -> MUST be skipped due to daily limit (max 2 per day)
    res3 = await send_push_notification(
        db=db_session,
        title="ТО 3",
        body="Нагадування 3 (має бути відхилено)",
        event_type="MAINTENANCE_DUE",
        generator_id=generator.id
    )
    assert res3.get("skipped") is True
    assert "Денний ліміт нагадувань про ТО" in res3.get("reason", "")


@pytest.mark.asyncio
async def test_push_notifications_routing_and_vapid_error_handling(client, superadmin_auth, operator_auth, db_session, monkeypatch):
    """
    Перевірка:
    1. Підписки суперадмінів завжди включаються до списку отримувачів незалежно від facility_id
    2. Тимчасові помилки мережі (HTTP 500/503) НЕ деактивують підписку
    3. Помилки 404/410 коректно деактивують застарілу підписку
    """
    import pywebpush

    # Subscribe superadmin to facility 2
    sub_payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/superadmin-test-token-777",
        "keys": {
            "p256dh": "BFdHB8a7vG8vNjOXCXHJ0cz0Diwh2fGJ42wpnMS5YWwdZlOMGaKEhiW1Gm8BeTBnE8xC9SoAkRlyD55ynQ_0pPE",
            "auth": "MDEyMzQ1Njc4OWFiY2RlZg"
        },
        "user_agent": "Pixel 8 SuperAdmin",
        "facility_id": 2
    }
    await client.post("/api/v1/notifications/subscribe", json=sub_payload, headers=superadmin_auth)

    # 1. Mock transient server error (HTTP 500) -> should NOT deactivate
    class FakeResponse500:
        status_code = 500
        reason = "Internal Server Error"
        text = "FCM temporary outage"

    def mock_webpush_500(*args, **kwargs):
        raise pywebpush.WebPushException("Server error", response=FakeResponse500())

    monkeypatch.setattr("pywebpush.webpush", mock_webpush_500)

    res = await send_push_notification(
        db=db_session,
        title="Запуск генератора",
        body="Генератор запущено на об'єкті 1",
        event_type="GENERATOR_START",
        facility_id=1
    )
    # Superadmin MUST be included in recipients_count even though facility_id=1 and subscription has facility_id=2
    assert res["recipients"] >= 1

    # Verify subscription is STILL ACTIVE after 500 error
    db_res = await db_session.execute(select(PushSubscription).where(PushSubscription.endpoint == sub_payload["endpoint"]))
    sub = db_res.scalars().first()
    assert sub is not None
    assert sub.is_active is True

    # 2. Mock 410 Gone -> subscription MUST be deactivated
    class FakeResponse410:
        status_code = 410
        reason = "Gone"
        text = "Subscription expired"

    def mock_webpush_410(*args, **kwargs):
        raise pywebpush.WebPushException("Gone", response=FakeResponse410())

    monkeypatch.setattr("pywebpush.webpush", mock_webpush_410)

    res_expired = await send_push_notification(
        db=db_session,
        title="Зупинка генератора",
        body="Генератор зупинено",
        event_type="GENERATOR_STOP",
        facility_id=1
    )
    assert res_expired["recipients"] >= 1

    # Verify subscription is now marked inactive
    await db_session.refresh(sub)
    assert sub.is_active is False
