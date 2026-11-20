import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from backend.app.models.facility import Facility
from backend.app.models.fuel import FuelReceipt, FuelStock
from backend.app.models.generator import Generator, GeneratorRun
from backend.app.models.maintenance import MaintenanceRecord, MaintenanceSchedule
from backend.app.models.notification import NotificationLog
from backend.app.models.user import User
from backend.app.services.report_service import generate_operational_report, generate_excel_report
from backend.app.services.settings_service import update_system_settings
from backend.app.services.weather_service import check_all_facilities_weather_warnings, clear_weather_cache


@pytest.mark.asyncio
async def test_report_cost_per_operating_hour_and_excel(db_session):
    user = (await db_session.execute(select(User).order_by(User.id.asc()))).scalars().first()
    assert user is not None

    fac = await db_session.get(Facility, 1)
    if not fac:
        fac = Facility(id=1, name="Об'єкт 1", address="м. Київ", city="Київ")
        db_session.add(fac)
        await db_session.flush()

    stock = FuelStock(facility_id=fac.id, name="Склад Тест", fuel_type="А-95", current_balance_l=100.0)
    db_session.add(stock)
    await db_session.flush()

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    rec = FuelReceipt(
        facility_id=fac.id,
        stock_id=stock.id,
        user_id=user.id,
        fuel_type="А-95",
        liters=50.0,
        price_per_liter=60.0,
        cost_total=3000.0,
        fuel_provider="wog",
        driver_name="Тест Водій",
        receipt_number="CHK-001",
        created_at=now_naive - timedelta(hours=2),
    )
    db_session.add(rec)

    gen = Generator(
        facility_id=fac.id,
        name="Ген Вартості",
        model="G-100",
        manufacturer="Honda",
        serial_number="SN-COST-1",
        rated_power_kw=10.0,
        tank_capacity_l=40.0,
        fuel_type="А-95",
        nominal_consumption_l_per_h=2.5,
        current_operating_hours=10.0,
        fuel_tank_level_l=20.0,
        status="STOPPED",
        is_configured=True,
    )
    db_session.add(gen)
    await db_session.flush()

    db_session.add(
        MaintenanceSchedule(
            generator_id=gen.id,
            interval_hours=200.0,
            last_performed_hours=0.0,
            next_due_hours=200.0,
        )
    )
    db_session.add(
        GeneratorRun(
            generator_id=gen.id,
            user_id=user.id,
            start_time=now_naive - timedelta(hours=6),
            end_time=now_naive - timedelta(hours=2),
            start_hours=6.0,
            end_hours=10.0,
            duration_hours=4.0,
            duration_seconds=14400,
            calculated_consumption_l=10.0,
            status="COMPLETED",
        )
    )
    db_session.add(
        MaintenanceRecord(
            generator_id=gen.id,
            user_id=user.id,
            maintenance_type="INTERMEDIATE",
            operating_hours=10.0,
            work_description="Заміна свічки",
            cost=400.0,
            created_at=now_naive - timedelta(hours=1),
        )
    )
    await db_session.commit()

    rep = await generate_operational_report(
        db_session,
        generator_id=gen.id,
        facility_id=fac.id,
        start_date=now_naive - timedelta(days=1),
        end_date=now_naive + timedelta(hours=1),
    )
    # 10 L consumed * 60 UAH/L = 600 UAH fuel; + 400 UAH maint = 1000 UAH / 4 hours = 250 UAH/h
    assert rep.effective_fuel_price_per_liter == pytest.approx(60.0)
    assert rep.fuel_consumed_cost_uah == pytest.approx(600.0)
    assert rep.operating_total_cost_uah == pytest.approx(1000.0)
    assert rep.fuel_cost_per_hour_uah == pytest.approx(150.0)
    assert rep.maintenance_cost_per_hour_uah == pytest.approx(100.0)
    assert rep.cost_per_operating_hour_uah == pytest.approx(250.0)

    excel_bytes = await generate_excel_report(
        db_session,
        generator_id=gen.id,
        facility_id=fac.id,
        start_date=now_naive - timedelta(days=1),
        end_date=now_naive + timedelta(hours=1),
    )
    assert excel_bytes[:2] == b"PK"


@pytest.mark.asyncio
async def test_facilities_network_overview_rbac_and_data(client, superadmin_auth, operator_auth, db_session):
    fac2 = Facility(name="Філія Львів", address="м. Львів, вул. Франка 10", city="Львів")
    db_session.add(fac2)
    await db_session.commit()
    await db_session.refresh(fac2)

    # Admin sees all facilities
    r_admin = await client.get("/api/v1/facilities/overview", headers=superadmin_auth)
    assert r_admin.status_code == 200
    body = r_admin.json()
    assert body["summary"]["total_facilities"] >= 2
    fac_ids = [f["id"] for f in body["facilities"]]
    assert fac2.id in fac_ids

    # Operator scoped strictly to facility 1
    r_op = await client.get("/api/v1/facilities/overview", headers=operator_auth)
    assert r_op.status_code == 200
    op_fac_ids = [f["id"] for f in r_op.json()["facilities"]]
    assert op_fac_ids == [1]
    assert fac2.id not in op_fac_ids


@pytest.mark.asyncio
async def test_weather_warning_push_threshold_and_deduplication(client, superadmin_auth, db_session):
    clear_weather_cache()
    # Configure min level = orange via notifications API
    r_set = await client.put(
        "/api/v1/notifications/settings",
        headers=superadmin_auth,
        json={
            "notifications_enabled": True,
            "notify_weather_warnings": True,
            "weather_warning_min_level": "orange",
        },
    )
    assert r_set.status_code == 200
    assert r_set.json()["weather_warning_min_level"] == "orange"

    mock_warnings = [
        {
            "id": "w-yellow",
            "level": "yellow",
            "level_num": 1,
            "level_ua": "Жовтий (I рівень)",
            "icon": "🌬️",
            "event": "Пориви вітру 15 м/с",
            "description": "Пориви вітру.",
            "areas_uk": ["Київській області", "Дніпропетровській області"],
            "areas_en": ["Kyiv oblast", "Dnipropetrovsk oblast"],
            "polygons": [],
            "onset": "2026-11-20T12:00:00+00:00",
            "expires": "2026-11-21T08:00:00+00:00",
            "period_formatted": "з 20.11 14:00 до 21.11 10:00",
            "source": "УкрГМЦ · MeteoAlarm",
        },
        {
            "id": "w-orange",
            "level": "orange",
            "level_num": 2,
            "level_ua": "Помаранчевий (II рівень)",
            "icon": "⛈️",
            "event": "Сильна гроза та град",
            "description": "Небезпечні шквали.",
            "areas_uk": ["Київській області", "Дніпропетровській області"],
            "areas_en": ["Kyiv oblast", "Dnipropetrovsk oblast"],
            "polygons": [],
            "onset": "2026-11-20T12:00:00+00:00",
            "expires": "2026-11-21T10:00:00+00:00",
            "period_formatted": "з 20.11 14:00 до 21.11 12:00",
            "source": "УкрГМЦ · MeteoAlarm",
        },
    ]

    with patch("backend.app.services.weather_service.fetch_meteoalarm_ukraine_warnings", new=AsyncMock(return_value=mock_warnings)):
        with patch("backend.app.services.weather_service._DISPATCHED_WEATHER_WARNINGS", {}):
            # Log a notification via real send_push_notification mock or let it write NotificationLog
            sent_first = await check_all_facilities_weather_warnings(db_session)
            assert sent_first >= 1

            # Check only orange warning was dispatched (yellow filtered out by threshold)
            from sqlalchemy import select
            logs = (
                await db_session.execute(
                    select(NotificationLog).where(NotificationLog.event_type == "WEATHER_WARNING")
                )
            ).scalars().all()
            assert any("Сильна гроза" in (l.body or "") for l in logs)
            assert not any("Пориви вітру 15 м/с" in (l.body or "") for l in logs)

            # Second run must deduplicate cleanly (0 new dispatches)
            sent_second = await check_all_facilities_weather_warnings(db_session)
            assert sent_second == 0

            # Even if in-memory cache is cleared, persistent NotificationLog prevents duplicates
            with patch("backend.app.services.weather_service._DISPATCHED_WEATHER_WARNINGS", {}):
                sent_third = await check_all_facilities_weather_warnings(db_session)
                assert sent_third == 0

    # Ensure yellow alerts do fire if admin lowers threshold to yellow
    await update_system_settings(db_session, {"weather_warning_min_level": "yellow"})
    with patch("backend.app.services.weather_service.fetch_meteoalarm_ukraine_warnings", new=AsyncMock(return_value=mock_warnings)):
        with patch("backend.app.services.weather_service._DISPATCHED_WEATHER_WARNINGS", {}):
            sent_yellow = await check_all_facilities_weather_warnings(db_session)
            assert sent_yellow >= 1
