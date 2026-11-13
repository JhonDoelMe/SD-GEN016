import datetime
from unittest.mock import patch, AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from backend.app.models.facility import Facility
from backend.app.models.generator import Generator, GeneratorRun, GeneratorSchedule
from backend.app.models.notification import NotificationLog
from backend.app.models.user import User, Role
from backend.app.core.security import get_password_hash
from backend.app.core.timezone import now_utc
from backend.app.services.settings_service import set_runtime_setting, update_system_settings
from backend.app.services.email_service import (
    _wrap_html_template,
    _format_from_header,
    generate_unsubscribe_token,
    verify_unsubscribe_token,
    build_unsubscribe_url,
    resolve_facility_email_recipients,
    send_empty_tank_email,
    send_critical_fault_email,
    send_maintenance_due_email,
    send_schedule_auto_stop_email,
    send_outside_work_hours_email,
)
from backend.app.services.notification_service import (
    check_and_notify_low_fuel,
    check_and_notify_maintenance_due,
    notify_critical_fault,
)
from backend.app.services.operational_guard_service import check_operational_guardrails


def test_email_template_product_branding_logo_and_unsubscribe():
    unsub_url = build_unsubscribe_url("operator@example.com", user_id=7)
    html_doc = _wrap_html_template(
        title="Тест листа",
        content_html="<p>Оперативне сповіщення</p>",
        unsubscribe_url=unsub_url,
        embed_logo=True,
    )

    assert "SD-GEN016" in html_doc
    assert "Service Desk Генератора" in html_doc
    assert "cid:sdgen-logo" in html_doc
    assert "Відписатися від розсилки" in html_doc
    assert unsub_url in html_doc
    assert "MAXI-UA LLC" not in html_doc

    formatted = _format_from_header("alerts@sdgen.pp.ua", "alerts@sdgen.pp.ua")
    assert "SD-GEN016" in formatted
    assert "alerts@sdgen.pp.ua" in formatted


@pytest.mark.asyncio
async def test_email_unsubscribe_one_click_and_resubscribe_flow(client, db_session, superadmin_auth):
    # Create an operator with an email via DB or API
    res = await client.post(
        "/api/v1/users",
        headers=superadmin_auth,
        json={
            "login": "mail_op",
            "password": "MailOpPass123!",
            "full_name": "Олена Пошта",
            "email": "mail_op@example.com",
            "role_ids": [3],
        },
    )
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]
    assert res.json()["email_notifications_enabled"] is True

    token = generate_unsubscribe_token("mail_op@example.com", user_id=user_id, action="unsub")
    parsed = verify_unsubscribe_token(token, expected_action="unsub")
    assert parsed is not None
    assert parsed["email"] == "mail_op@example.com"
    assert parsed["user_id"] == user_id

    # Bad token must fail with 400
    bad_get = await client.get("/api/v1/email/unsubscribe", params={"token": "invalid.token.sig"})
    assert bad_get.status_code == 400

    # Valid GET unsubscribe renders resubscribe form and disables flag
    ok_get = await client.get("/api/v1/email/unsubscribe", params={"token": token})
    assert ok_get.status_code == 200
    assert "/api/v1/email/resubscribe" in ok_get.text

    u_row = (await db_session.execute(select(User).where(User.id == user_id))).scalars().first()
    assert u_row.email_notifications_enabled is False

    # Resubscribe via form token
    resub_token = generate_unsubscribe_token("mail_op@example.com", user_id=user_id, action="resub")
    resub_resp = await client.post("/api/v1/email/resubscribe", data={"token": resub_token})
    assert resub_resp.status_code == 200

    await db_session.refresh(u_row)
    assert u_row.email_notifications_enabled is True

    # RFC 8058 One-Click POST unsubscribe
    one_click_resp = await client.post(
        "/api/v1/email/unsubscribe",
        params={"token": token},
        data={"List-Unsubscribe": "One-Click"},
    )
    assert one_click_resp.status_code == 200
    assert one_click_resp.json()["status"] == "unsubscribed"

    await db_session.refresh(u_row)
    assert u_row.email_notifications_enabled is False


@pytest.mark.asyncio
async def test_resolve_facility_recipients_and_opt_out_filtering(db_session):
    fac1 = Facility(name="Об'єкт 1")
    fac2 = Facility(name="Об'єкт 2")
    db_session.add_all([fac1, fac2])
    await db_session.flush()

    admin_role = (await db_session.execute(select(Role).where(Role.name == "admin"))).scalars().first()
    op_role = (await db_session.execute(select(Role).where(Role.name == "operator"))).scalars().first()

    u_fac1_admin = User(
        login="f1_admin",
        password_hash=get_password_hash("Pass1234!"),
        full_name="Адмін 1",
        email="f1admin@example.com",
        facility_id=fac1.id,
        is_active=True,
        email_notifications_enabled=True,
        roles=[admin_role],
    )
    u_fac1_opted_out = User(
        login="f1_optout",
        password_hash=get_password_hash("Pass1234!"),
        full_name="Відписаний 1",
        email="optedout@example.com",
        facility_id=fac1.id,
        is_active=True,
        email_notifications_enabled=False,
        roles=[op_role],
    )
    u_fac2_admin = User(
        login="f2_admin",
        password_hash=get_password_hash("Pass1234!"),
        full_name="Адмін 2",
        email="f2admin@example.com",
        facility_id=fac2.id,
        is_active=True,
        email_notifications_enabled=True,
        roles=[admin_role],
    )
    db_session.add_all([u_fac1_admin, u_fac1_opted_out, u_fac2_admin])
    await db_session.commit()

    set_runtime_setting("email_weekly_recipients", "optedout@example.com, extra@example.com")

    recs = await resolve_facility_email_recipients(db_session, facility_id=fac1.id)
    rec_emails = {addr for addr, _uid in recs}

    assert "f1admin@example.com" in rec_emails
    assert "extra@example.com" in rec_emails
    assert "optedout@example.com" not in rec_emails
    assert "f2admin@example.com" not in rec_emails


@pytest.mark.asyncio
async def test_empty_tank_critical_fault_and_rfc8058_headers_sent(db_session):
    fac = Facility(name="Котельня Центр")
    db_session.add(fac)
    await db_session.flush()

    admin_role = (await db_session.execute(select(Role).where(Role.name == "admin"))).scalars().first()
    u_admin = User(
        login="tank_admin",
        password_hash=get_password_hash("Pass1234!"),
        full_name="Інженер Баку",
        email="tankadmin@example.com",
        facility_id=fac.id,
        is_active=True,
        email_notifications_enabled=True,
        roles=[admin_role],
    )
    gen = Generator(
        facility_id=fac.id,
        name="GEN-EMPTY-01",
        model="SD-50",
        manufacturer="SDGen",
        serial_number="SN-EMPTY-01",
        tank_capacity_l=100.0,
        nominal_consumption_l_per_h=5.0,
        fuel_tank_level_l=0.0,
        current_operating_hours=10.0,
        is_active=True,
    )
    db_session.add_all([u_admin, gen])
    await db_session.commit()

    await update_system_settings(
        db_session,
        {
            "smtp_enabled": True,
            "smtp_primary_host": "smtp.gmail.com",
            "smtp_primary_user": "noreply@sdgen.pp.ua",
            "smtp_primary_password": "secret",
            "email_notify_empty_tank": True,
            "email_notify_critical_fault": True,
            "notifications_enabled": True,
            "notify_low_fuel": True,
            "notify_critical_faults": True,
        },
    )

    with patch("backend.app.services.email_service.send_smtp_message_sync") as mock_smtp:
        mock_smtp.return_value = None
        await check_and_notify_low_fuel(db_session, gen, 0.0)

        # EMPTY_TANK NotificationLog must be recorded
        empty_logs = (
            await db_session.execute(select(NotificationLog).where(NotificationLog.event_type == "EMPTY_TANK"))
        ).scalars().all()
        assert len(empty_logs) == 1
        assert "ПОРОЖНІЙ БАК" in empty_logs[0].title

        # Email sent with List-Unsubscribe + List-Unsubscribe-Post headers
        assert mock_smtp.call_count >= 1
        smtp_call_kwargs = mock_smtp.call_args[1]
        extra_headers = smtp_call_kwargs.get("extra_headers") or {}
        assert "List-Unsubscribe" in extra_headers
        assert extra_headers.get("List-Unsubscribe-Post") == "List-Unsubscribe=One-Click"
        assert "cid:sdgen-logo" in smtp_call_kwargs["html_body"]

        # Critical fault triggers both notification log and email
        mock_smtp.reset_mock()
        await notify_critical_fault(db_session, gen, "Перегрів", "Температура > 105°C")
        assert mock_smtp.call_count >= 1
        fault_logs = (
            await db_session.execute(select(NotificationLog).where(NotificationLog.event_type == "CRITICAL_FAULT"))
        ).scalars().all()
        assert len(fault_logs) == 1


@pytest.mark.asyncio
async def test_outside_work_hours_alert_when_autostop_disabled(db_session):
    fac = Facility(name="Об'єкт Графіку")
    db_session.add(fac)
    await db_session.flush()

    admin_role = (await db_session.execute(select(Role).where(Role.name == "admin"))).scalars().first()
    u_admin = User(
        login="sched_admin",
        password_hash=get_password_hash("Pass1234!"),
        full_name="Черговий Адмін",
        email="schedadmin@example.com",
        facility_id=fac.id,
        is_active=True,
        email_notifications_enabled=True,
        roles=[admin_role],
    )
    gen = Generator(
        facility_id=fac.id,
        name="GEN-SCHED-01",
        model="SD-30",
        manufacturer="SDGen",
        serial_number="SN-SCHED-01",
        tank_capacity_l=80.0,
        nominal_consumption_l_per_h=3.0,
        fuel_tank_level_l=50.0,
        current_operating_hours=20.0,
        timezone="Europe/Kyiv",
        is_active=True,
        status="RUNNING",
    )
    db_session.add_all([u_admin, gen])
    await db_session.flush()

    sched = GeneratorSchedule(
        generator_id=gen.id,
        weekday=-1,
        start_time="08:00",
        end_time="18:00",
        timezone="Europe/Kyiv",
        is_active=True,
    )
    outside_utc = datetime.datetime(2026, 11, 13, 20, 15)  # 22:15 in Europe/Kyiv
    run = GeneratorRun(
        generator_id=gen.id,
        user_id=u_admin.id,
        status="RUNNING",
        start_time=(outside_utc - datetime.timedelta(hours=1)),
        start_hours=20.0,
        start_fuel_level_l=50.0,
    )
    db_session.add_all([sched, run])
    await db_session.commit()

    await update_system_settings(
        db_session,
        {
            "enforce_work_schedule": True,
            "auto_stop_on_schedule_end": False,
            "notify_outside_schedule": True,
            "email_notify_outside_schedule": True,
            "smtp_enabled": True,
            "smtp_primary_host": "smtp.gmail.com",
            "smtp_primary_user": "noreply@sdgen.pp.ua",
            "smtp_primary_password": "secret",
            "notifications_enabled": True,
        },
    )

    with patch("backend.app.services.operational_guard_service.now_utc", return_value=outside_utc):
        with patch("backend.app.services.email_service.send_smtp_message_sync") as mock_smtp:
            mock_smtp.return_value = None
            await check_operational_guardrails(db_session)

            logs = (
                await db_session.execute(
                    select(NotificationLog).where(NotificationLog.event_type == "OUTSIDE_WORK_HOURS")
                )
            ).scalars().all()
            assert len(logs) == 1
            assert "поза" in logs[0].title.lower() or "графіка" in logs[0].body.lower()
            assert mock_smtp.call_count >= 1


@pytest.mark.asyncio
async def test_notification_bell_feed_scoping_and_mark_read(client, db_session, superadmin_auth, viewer_auth):
    fac1 = Facility(name="Філія А")
    fac2 = Facility(name="Філія Б")
    db_session.add_all([fac1, fac2])
    await db_session.flush()

    # Bind viewer1 to fac1
    viewer = (await db_session.execute(select(User).where(User.login == "viewer1"))).scalars().first()
    viewer.facility_id = fac1.id
    viewer.notifications_read_at = None

    now = now_utc(naive=True)
    l_fac1 = NotificationLog(
        event_type="EMPTY_TANK",
        facility_id=fac1.id,
        title="Порожній бак А",
        body="0 л",
        recipients_count=0,
        success_count=0,
        failure_count=0,
        created_at=now - datetime.timedelta(minutes=5),
    )
    l_fac2 = NotificationLog(
        event_type="LOW_FUEL",
        facility_id=fac2.id,
        title="Низьке паливо Б",
        body="3 л",
        recipients_count=0,
        success_count=0,
        failure_count=0,
        created_at=now - datetime.timedelta(minutes=3),
    )
    l_email_internal = NotificationLog(
        event_type="EMAIL_SENT",
        facility_id=fac1.id,
        title="Internal email log",
        body="should be hidden",
        recipients_count=1,
        success_count=1,
        failure_count=0,
        created_at=now - datetime.timedelta(minutes=1),
    )
    db_session.add_all([l_fac1, l_fac2, l_email_internal])
    await db_session.commit()

    # Viewer can access /feed (unlike /logs), sees only fac1 + global, excludes EMAIL_SENT
    feed_res = await client.get("/api/v1/notifications/feed", headers=viewer_auth)
    assert feed_res.status_code == 200
    feed_data = feed_res.json()
    titles = [item["title"] for item in feed_data["items"]]
    assert "Порожній бак А" in titles
    assert "Низьке паливо Б" not in titles
    assert "Internal email log" not in titles
    assert feed_data["unread_count"] >= 1

    # Mark all read -> unread_count drops to 0 and stays 0 on next /feed
    read_res = await client.post("/api/v1/notifications/read", headers=viewer_auth)
    assert read_res.status_code == 200
    assert read_res.json()["unread_count"] == 0

    feed_after = await client.get("/api/v1/notifications/feed", headers=viewer_auth)
    assert feed_after.status_code == 200
    assert feed_after.json()["unread_count"] == 0

    # Superadmin sees both facilities when not filtered
    sa_feed = await client.get("/api/v1/notifications/feed", headers=superadmin_auth)
    sa_titles = [item["title"] for item in sa_feed.json()["items"]]
    assert "Порожній бак А" in sa_titles
    assert "Низьке паливо Б" in sa_titles


@pytest.mark.asyncio
async def test_check_all_facilities_air_alerts_does_not_fail_on_facility_query(db_session):
    from backend.app.services.alert_service import check_all_facilities_air_alerts

    fac = Facility(name="Об'єкт Тривог", city="Київ")
    db_session.add(fac)
    await db_session.commit()

    with patch("backend.app.services.alert_service.get_facility_alert", new=AsyncMock(return_value={"is_active": False})) as mock_get:
        await check_all_facilities_air_alerts(db_session)
        called_ids = [call.args[1] for call in mock_get.await_args_list]
        assert fac.id in called_ids

