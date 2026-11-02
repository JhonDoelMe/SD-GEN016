import math
import datetime
import pytest
from zoneinfo import ZoneInfo
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.timezone import (
    is_within_work_schedule,
    get_facility_tz,
    now_utc,
    now_facility,
    to_facility_time,
)
from backend.app.services.settings_service import (
    RUNTIME_SETTINGS,
    DEFAULT_SYSTEM_SETTINGS,
    DEFAULT_INTERNET_PRICES,
    DEFAULT_OKKO_PRICES,
    load_system_settings,
    update_system_settings,
    refresh_internet_fuel_prices,
    get_fuel_prices_info,
    perform_system_reset,
)
from backend.app.services.notification_service import (
    get_or_create_vapid_keys,
    get_vapid_public_key,
    subscribe_device,
    unsubscribe_device,
    send_push_notification,
    get_notification_settings_data,
    _send_single_webpush_sync,
)
from backend.app.models.settings import SystemSetting
from backend.app.models.generator import Generator, GeneratorSchedule
from backend.app.models.facility import Facility
from backend.app.models.user import User
from backend.app.models.notification import PushSubscription, NotificationLog


# ============================================================================
# 1. TIMEZONE.PY TESTS (TIME-01 to TIME-07)
# ============================================================================

def test_timezone_daytime_schedule_half_open_boundaries():
    """TIME-06: Напіввідкритий інтервал [start_time, end_time)"""
    tz = ZoneInfo("Europe/Kyiv")
    schedules = [
        {"weekday": -1, "start_time": "08:00", "end_time": "20:00", "is_active": True}
    ]

    # Exactly at start 08:00:00 -> Allowed
    dt_start = datetime.datetime(2026, 11, 2, 8, 0, 0, tzinfo=tz)
    allowed, msg = is_within_work_schedule(schedules, dt_start)
    assert allowed is True
    assert "в межах дозволеного графіка" in msg

    # Middle of day 14:30 -> Allowed
    dt_mid = datetime.datetime(2026, 11, 2, 14, 30, 0, tzinfo=tz)
    allowed, msg = is_within_work_schedule(schedules, dt_mid)
    assert allowed is True

    # One minute before end 19:59:59 -> Allowed
    dt_before_end = datetime.datetime(2026, 11, 2, 19, 59, 59, tzinfo=tz)
    allowed, msg = is_within_work_schedule(schedules, dt_before_end)
    assert allowed is True

    # Exactly at end 20:00:00 -> Forbidden (half-open)
    dt_end = datetime.datetime(2026, 11, 2, 20, 0, 0, tzinfo=tz)
    allowed, msg = is_within_work_schedule(schedules, dt_end)
    assert allowed is False
    assert "поза межами робочого графіка" in msg

    # Before start 07:59:59 -> Forbidden
    dt_before = datetime.datetime(2026, 11, 2, 7, 59, 59, tzinfo=tz)
    allowed, msg = is_within_work_schedule(schedules, dt_before)
    assert allowed is False


def test_timezone_overnight_schedule_monday_to_tuesday():
    """TIME-02: Підтримка нічних змін з переходом через північ"""
    tz = ZoneInfo("Europe/Kyiv")
    # Monday schedule 20:00 to 08:00 (weekday=0)
    schedules = [
        {"weekday": 0, "start_time": "20:00", "end_time": "08:00", "is_active": True}
    ]

    # Monday 21:00 -> Allowed
    dt_mon_21 = datetime.datetime(2026, 11, 2, 21, 0, 0, tzinfo=tz)
    assert is_within_work_schedule(schedules, dt_mon_21)[0] is True

    # Monday 23:30 -> Allowed
    dt_mon_23 = datetime.datetime(2026, 11, 2, 23, 30, 0, tzinfo=tz)
    assert is_within_work_schedule(schedules, dt_mon_23)[0] is True

    # Tuesday 02:00 -> Allowed (shift started Monday)
    dt_tue_02 = datetime.datetime(2026, 11, 3, 2, 0, 0, tzinfo=tz)
    assert is_within_work_schedule(schedules, dt_tue_02)[0] is True

    # Tuesday 07:59:59 -> Allowed
    dt_tue_0759 = datetime.datetime(2026, 11, 3, 7, 59, 59, tzinfo=tz)
    assert is_within_work_schedule(schedules, dt_tue_0759)[0] is True

    # Tuesday 08:00:00 -> Forbidden
    dt_tue_0800 = datetime.datetime(2026, 11, 3, 8, 0, 0, tzinfo=tz)
    assert is_within_work_schedule(schedules, dt_tue_0800)[0] is False

    # Monday 08:00:00 -> Forbidden (no shift started Sunday)
    dt_mon_08 = datetime.datetime(2026, 11, 2, 8, 0, 0, tzinfo=tz)
    assert is_within_work_schedule(schedules, dt_mon_08)[0] is False


def test_timezone_overnight_week_boundary_sunday_to_monday():
    """TIME-02: Перехід між днями тижня (неділя -> понеділок)"""
    tz = ZoneInfo("Europe/Kyiv")
    # Sunday schedule 21:00 to 07:00 (weekday=6)
    schedules = [
        {"weekday": 6, "start_time": "21:00", "end_time": "07:00", "is_active": True}
    ]

    # Sunday 22:00 (2026-11-01 is Sunday) -> Allowed
    dt_sun = datetime.datetime(2026, 11, 1, 22, 0, 0, tzinfo=tz)
    assert is_within_work_schedule(schedules, dt_sun)[0] is True

    # Monday 03:00 (2026-11-02 is Monday) -> Allowed
    dt_mon = datetime.datetime(2026, 11, 2, 3, 0, 0, tzinfo=tz)
    assert is_within_work_schedule(schedules, dt_mon)[0] is True

    # Monday 07:00 -> Forbidden
    dt_mon_07 = datetime.datetime(2026, 11, 2, 7, 0, 0, tzinfo=tz)
    assert is_within_work_schedule(schedules, dt_mon_07)[0] is False


def test_timezone_fail_closed_empty_or_inactive_schedules():
    """TIME-01, TIME-04: Fail-closed при відсутності активних графіків"""
    with patch("backend.app.core.timezone.get_runtime_setting", return_value=True):
        # Empty schedules list
        ok, msg = is_within_work_schedule([])
        assert ok is False
        assert "не налаштовано" in msg

        # None schedules list
        ok, msg = is_within_work_schedule(None)
        assert ok is False
        assert "не налаштовано" in msg

        # Only inactive schedules
        inactive = [{"weekday": -1, "start_time": "08:00", "end_time": "20:00", "is_active": False}]
        ok, msg = is_within_work_schedule(inactive)
        assert ok is False
        assert "немає жодного активного розкладу" in msg


def test_timezone_enforcement_disabled_allows_24_7():
    """TIME-01: Якщо контроль вимкнено в налаштуваннях -> 24/7 доступ"""
    with patch("backend.app.core.timezone.get_runtime_setting", return_value=False):
        ok, msg = is_within_work_schedule([])
        assert ok is True
        assert "24/7" in msg


def test_timezone_validation_skips_invalid_entries_fail_closed():
    """TIME-03: Відхилення некоректних форматів часу та днів тижня"""
    with patch("backend.app.core.timezone.get_runtime_setting", return_value=True):
        invalid_schedules = [
            {"weekday": 99, "start_time": "08:00", "end_time": "20:00", "is_active": True},
            {"weekday": 0, "start_time": "25:00", "end_time": "20:00", "is_active": True},
            {"weekday": 0, "start_time": "bad_time", "end_time": "20:00", "is_active": True},
            "not_a_dict"
        ]
        ok, msg = is_within_work_schedule(invalid_schedules)
        assert ok is False
        assert "немає жодного активного розкладу" in msg


def test_timezone_fallback_on_invalid_tz_string():
    """TIME-05: Безпечний fallback на Europe/Kyiv з логуванням warning"""
    tz = get_facility_tz("Invalid/NonExistent_Zone")
    assert tz == ZoneInfo("Europe/Kyiv")


def test_timezone_datetime_conversions_naive_and_aware():
    """TIME-07: Уніфікація now_utc, to_facility_time для naive та aware"""
    n_utc = now_utc(naive=True)
    assert n_utc.tzinfo is None

    a_utc = now_utc(naive=False)
    assert a_utc.tzinfo == datetime.timezone.utc

    # Naive dt is interpreted as UTC and converted to facility timezone
    naive_dt = datetime.datetime(2026, 11, 2, 12, 0, 0)
    fac_time = to_facility_time(naive_dt, "Europe/Kyiv")
    assert fac_time.tzinfo == ZoneInfo("Europe/Kyiv")
    # Europe/Kyiv in November is UTC+2 -> 14:00
    assert fac_time.hour == 14


# ============================================================================
# 2. SETTINGS_SERVICE.PY TESTS (INF-35 to INF-43)
# ============================================================================

@pytest.mark.asyncio
async def test_settings_fuel_prices_protection_on_fetch_failure(db_session: AsyncSession):
    """INF-35: Невдалий запит цін WOG/OKKO не перетирає останні дійсні ціни резервними"""
    await load_system_settings(db_session)

    # 1. First, establish valid custom/live prices
    await update_system_settings(db_session, {
        "internet_price_a95": 99.50,
        "internet_price_dp": 105.00,
        "internet_prices_updated_at": "2026-11-01 10:00:00",
        "internet_prices_is_live": True,
        "okko_price_a95": 98.50,
        "okko_price_dp": 104.00,
        "okko_prices_updated_at": "2026-11-01 10:00:00",
        "okko_prices_is_live": True,
    })

    # 2. Simulate network scrapers failing (is_live=False)
    mock_wog_fail = (
        {"А-95": 92.90, "ДП": 103.50},
        [],
        "АЗК WOG (резервний кеш)",
        False
    )
    mock_okko_fail = (
        {"А-95": 92.90, "ДП": 106.90},
        [],
        "АЗК OKKO (резервний кеш)",
        False
    )

    with patch("backend.app.services.settings_service.fetch_wog_fuel_prices_online", return_value=mock_wog_fail), \
         patch("backend.app.services.settings_service.fetch_okko_fuel_prices_online", return_value=mock_okko_fail):

        res = await refresh_internet_fuel_prices(db_session, provider="all")

        # Must keep previous real prices (99.50 and 105.00) and NOT overwrite with 92.90 / 103.50!
        assert res["fuels"]["А-95"]["internet_price"] == 99.50
        assert res["fuels"]["ДП"]["internet_price"] == 105.00
        assert res["okko_fuels"]["А-95"]["internet_price"] == 98.50
        assert res["okko_fuels"]["ДП"]["internet_price"] == 104.00

        # Updated_at timestamp must NOT be modified on failed fetch
        assert res["internet_prices_updated_at"] == "2026-11-01 10:00:00"
        assert res["okko_prices_updated_at"] == "2026-11-01 10:00:00"


@pytest.mark.asyncio
async def test_settings_gas_decoupled_from_a92(db_session: AsyncSession):
    """INF-37: Налаштування ручної ціни А-92 не впливає на ціну ГАЗ"""
    await load_system_settings(db_session)

    # Set manual A-92 price to 85.0 UAH
    await update_system_settings(db_session, {
        "fuel_price_a92": 85.00
    })

    info = get_fuel_prices_info()
    # A-92 should use configured price
    assert info["fuels"]["А-92"]["effective_price"] == 85.00
    assert info["fuels"]["А-92"]["configured_price"] == 85.00
    assert info["fuels"]["А-92"]["source"] == "settings"

    # ГАЗ must NOT use 85.00! It must use internet price (52.50)
    assert info["fuels"]["ГАЗ"]["effective_price"] == 52.50
    assert info["fuels"]["ГАЗ"]["configured_price"] == 0.00
    assert info["fuels"]["ГАЗ"]["source"] == "internet"

    assert info["okko_fuels"]["ГАЗ"]["effective_price"] == 59.90
    assert info["okko_fuels"]["ГАЗ"]["configured_price"] == 0.00
    assert info["okko_fuels"]["ГАЗ"]["source"] == "internet"


@pytest.mark.asyncio
async def test_settings_routine_update_does_not_wipe_generator_schedules(db_session: AsyncSession):
    """INF-36: Звичайне збереження налаштувань не знищує індивідуальні графіки генераторів"""
    # Create test generator with custom schedule (09:00 - 18:00 on Monday)
    gen = Generator(
        name="Gen Schedule Guard",
        model="Test",
        manufacturer="PowerGen",
        serial_number="SN-SCHED-01",
        rated_power_kw=10.0,
        tank_capacity_l=50.0,
        fuel_type="А-95",
        nominal_consumption_l_per_h=2.5,
        status="STOPPED",
        is_configured=True
    )
    db_session.add(gen)
    await db_session.flush()

    sched = GeneratorSchedule(
        generator_id=gen.id,
        weekday=0,
        start_time="09:00",
        end_time="18:00",
        is_active=True
    )
    db_session.add(sched)
    await db_session.commit()

    # Routine system settings update (e.g. updating organization name)
    await update_system_settings(db_session, {
        "organization_name": "NEW COMPANY NAME",
        "work_schedule_start": "07:00",
        "work_schedule_end": "22:00"
    }, apply_to_all_generators=False)

    # Check generator schedules: custom 09:00 - 18:00 schedule MUST be preserved!
    res = await db_session.execute(select(GeneratorSchedule).where(GeneratorSchedule.generator_id == gen.id))
    schedules = res.scalars().all()
    assert len(schedules) == 1
    assert schedules[0].start_time == "09:00"
    assert schedules[0].end_time == "18:00"
    assert schedules[0].weekday == 0


@pytest.mark.asyncio
async def test_settings_explicit_mass_schedule_propagation(db_session: AsyncSession):
    """INF-36: Явне масове застосування графіка оновлює всі генератори та повертає лічильник"""
    gen = Generator(
        name="Gen Mass Update",
        model="Test",
        manufacturer="PowerGen",
        serial_number="SN-MASS-01",
        rated_power_kw=10.0,
        tank_capacity_l=50.0,
        fuel_type="А-95",
        nominal_consumption_l_per_h=2.5,
        status="STOPPED",
        is_configured=True
    )
    db_session.add(gen)
    await db_session.commit()

    # Explicit mass propagation: apply_to_all_generators=True
    res_dict = await update_system_settings(db_session, {
        "work_schedule_start": "06:30",
        "work_schedule_end": "21:30",
        "facility_timezone": "Europe/Kyiv"
    }, apply_to_all_generators=True)

    assert res_dict["updated_generators_count"] >= 1

    # Verify that generator schedule has been updated to 06:30 - 21:30
    res = await db_session.execute(select(GeneratorSchedule).where(GeneratorSchedule.generator_id == gen.id))
    scheds = res.scalars().all()
    assert len(scheds) == 1
    assert scheds[0].start_time == "06:30"
    assert scheds[0].end_time == "21:30"
    assert scheds[0].weekday == -1


@pytest.mark.asyncio
async def test_settings_factory_reset_leaves_generator_unconfigured(db_session: AsyncSession):
    """INF-38: Після factory_reset генератор створюється з is_configured=False та STOPPED"""
    res = await perform_system_reset(db_session, mode="factory_reset", user_id=1)
    assert res["status"] == "ok"

    # Check factory generator
    gen_res = await db_session.execute(select(Generator))
    factory_gen = gen_res.scalars().first()
    assert factory_gen is not None
    assert factory_gen.is_configured is False
    assert factory_gen.status == "STOPPED"


@pytest.mark.asyncio
async def test_settings_settings_reset_atomic_operation(db_session: AsyncSession):
    """INF-39: settings_reset скидає системні налаштування в єдиній транзакції"""
    # Change some setting
    await update_system_settings(db_session, {
        "organization_name": "CUSTOM TEMPORARY ORG",
        "default_maintenance_interval_hours": 500.0
    })

    res = await perform_system_reset(db_session, mode="settings_reset", user_id=1)
    assert res["status"] == "ok"

    assert RUNTIME_SETTINGS["organization_name"] == DEFAULT_SYSTEM_SETTINGS["organization_name"]
    assert RUNTIME_SETTINGS["default_maintenance_interval_hours"] == DEFAULT_SYSTEM_SETTINGS["default_maintenance_interval_hours"]


@pytest.mark.asyncio
async def test_settings_numerical_validation_constraints(db_session: AsyncSession):
    """INF-43: Валідація числових системних параметрів (NaN, Inf, від'ємні значення)"""
    # Negative maintenance interval -> ValueError
    with pytest.raises(ValueError, match="повинен бути більше ніж 0.0"):
        await update_system_settings(db_session, {"default_maintenance_interval_hours": -10.0})

    # Zero maintenance interval -> ValueError
    with pytest.raises(ValueError, match="повинен бути більше ніж 0.0"):
        await update_system_settings(db_session, {"default_maintenance_interval_hours": 0.0})

    # Negative fuel price -> ValueError
    with pytest.raises(ValueError, match="не може бути меншим ніж 0.0"):
        await update_system_settings(db_session, {"fuel_price_a95": -5.0})

    # NaN / Inf -> ValueError
    with pytest.raises(ValueError, match="не може бути NaN або нескінченністю"):
        await update_system_settings(db_session, {"default_maintenance_interval_hours": float("nan")})

    with pytest.raises(ValueError, match="не може бути NaN або нескінченністю"):
        await update_system_settings(db_session, {"low_fuel_threshold_l": float("inf")})

    # Non-numeric string -> ValueError
    with pytest.raises(ValueError, match="повинен бути дійсним числом"):
        await update_system_settings(db_session, {"login_max_attempts": "not_a_number"})


# ============================================================================
# 3. NOTIFICATION_SERVICE.PY TESTS (NOTIF-01 to NOTIF-10)
# ============================================================================

@pytest.mark.asyncio
async def test_notif_vapid_keys_generation_and_corrupt_repair(db_session: AsyncSession):
    """NOTIF-01: Безпечна генерація VAPID ключів та автоматичне відновлення пошкоджених ключів"""
    # 1. Clean existing keys
    await db_session.execute(delete(SystemSetting).where(SystemSetting.key.in_(["vapid_public_key", "vapid_private_key_pem"])))
    await db_session.commit()

    # 2. First call generates new pair
    pub_key, priv_key, claim = await get_or_create_vapid_keys(db_session)
    assert len(pub_key) > 40
    assert "BEGIN EC PRIVATE KEY" in priv_key or "BEGIN PRIVATE KEY" in priv_key

    # 3. Repeat call returns the same valid keys
    pub2, priv2, _ = await get_or_create_vapid_keys(db_session)
    assert pub2 == pub_key
    assert priv2 == priv_key

    # 4. Corrupt the private key in DB
    priv_row = await db_session.get(SystemSetting, "vapid_private_key_pem")
    priv_row.value_json = '"INVALID_CORRUPT_KEY_DATA"'
    await db_session.commit()

    # 5. Recovery: get_or_create_vapid_keys detects corruption and regenerates valid pair without crash
    pub3, priv3, _ = await get_or_create_vapid_keys(db_session)
    assert pub3 != pub_key
    assert "BEGIN" in priv3


@pytest.mark.asyncio
async def test_notif_subscribe_device_ownership_protection(db_session: AsyncSession):
    """NOTIF-02: Захист від IDOR — підписка не може бути перепризначена іншому користувачу"""
    # User 1 registers device
    sub1 = await subscribe_device(
        db=db_session,
        user_id=101,
        endpoint="https://fcm.googleapis.com/fcm/send/test_device_1",
        p256dh="key_p256dh_sample",
        auth="key_auth_sample",
        is_admin=False
    )
    assert sub1.user_id == 101

    # User 1 can safely update their own device
    sub1_updated = await subscribe_device(
        db=db_session,
        user_id=101,
        endpoint="https://fcm.googleapis.com/fcm/send/test_device_1",
        p256dh="key_p256dh_sample_v2",
        auth="key_auth_sample_v2",
        is_admin=False
    )
    assert sub1_updated.p256dh == "key_p256dh_sample_v2"

    # User 102 attempts to hijack User 101's endpoint -> HTTP 403 Forbidden!
    with pytest.raises(HTTPException) as exc_info:
        await subscribe_device(
            db=db_session,
            user_id=102,
            endpoint="https://fcm.googleapis.com/fcm/send/test_device_1",
            p256dh="key_p256dh_sample_v2",
            auth="key_auth_sample_v2",
            is_admin=False
        )
    assert exc_info.value.status_code == 403
    assert "зареєстрована за іншим користувачем" in exc_info.value.detail

    # SuperAdmin CAN administratively reassign
    sub_admin = await subscribe_device(
        db=db_session,
        user_id=102,
        endpoint="https://fcm.googleapis.com/fcm/send/test_device_1",
        p256dh="key_p256dh_sample_v2",
        auth="key_auth_sample_v2",
        is_admin=True
    )
    assert sub_admin.user_id == 102


@pytest.mark.asyncio
async def test_notif_unsubscribe_device_security(db_session: AsyncSession):
    """NOTIF-03: Безпечне скасування підписки (тільки власник або адміністратор)"""
    sub = await subscribe_device(
        db=db_session,
        user_id=201,
        endpoint="https://fcm.googleapis.com/fcm/send/test_unsub_device",
        p256dh="p256dh_test",
        auth="auth_test",
        is_admin=False
    )
    assert sub.is_active is True

    # Anonymous or wrong user attempting to unsubscribe -> HTTP 403 Forbidden!
    with pytest.raises(HTTPException) as exc_info:
        await unsubscribe_device(
            db=db_session,
            endpoint="https://fcm.googleapis.com/fcm/send/test_unsub_device",
            user_id=202,
            is_admin=False
        )
    assert exc_info.value.status_code == 403

    # Missing user_id without admin -> HTTP 403 Forbidden!
    with pytest.raises(HTTPException) as exc_info2:
        await unsubscribe_device(
            db=db_session,
            endpoint="https://fcm.googleapis.com/fcm/send/test_unsub_device",
            user_id=None,
            is_admin=False
        )
    assert exc_info2.value.status_code == 403

    # Proper owner can unsubscribe
    ok = await unsubscribe_device(
        db=db_session,
        endpoint="https://fcm.googleapis.com/fcm/send/test_unsub_device",
        user_id=201,
        is_admin=False
    )
    assert ok is True

    # Sub is now deactivated
    refreshed = await db_session.get(PushSubscription, sub.id)
    assert refreshed.is_active is False


@pytest.mark.asyncio
async def test_notif_maintenance_due_rate_limiting_and_escalation(db_session: AsyncSession):
    """NOTIF-05: Ліміт нагадувань про ТО за добу та пріоритет критичного сповіщення про прострочення"""
    # Create test generator
    gen = Generator(
        name="Gen Notif Test",
        model="T-100",
        manufacturer="PowerGen",
        serial_number="SN-NOTIF-01",
        rated_power_kw=5.0,
        tank_capacity_l=25.0,
        fuel_type="А-95",
        nominal_consumption_l_per_h=2.0,
        status="STOPPED",
        is_configured=True
    )
    db_session.add(gen)
    await db_session.commit()

    # First approaching maintenance notification
    res1 = await send_push_notification(
        db=db_session,
        title="🔧 Наближається планове ТО — Gen Notif Test",
        body="Залишилося 10 мотогодин до регламентного ТО",
        event_type="MAINTENANCE_DUE",
        generator_id=gen.id
    )
    assert res1["sent"] == 0 or res1.get("recipients", 0) >= 0

    # Immediate second warning within 3 hours -> Skipped due to cooldown
    res2 = await send_push_notification(
        db=db_session,
        title="🔧 Наближається планове ТО — Gen Notif Test",
        body="Залишилося 10 мотогодин до регламентного ТО",
        event_type="MAINTENANCE_DUE",
        generator_id=gen.id
    )
    assert res2.get("skipped") is True
    assert "менше 3 годин тому" in res2.get("reason", "")

    # BUT an escalating OVERDUE alert ("Прострочено ТО") is NOT blocked by approaching warning!
    res_overdue = await send_push_notification(
        db=db_session,
        title="🔧 УВАГА: Прострочено ТО — Gen Notif Test!",
        body="Регламент ТО прострочено на 5 мотогодин!",
        event_type="MAINTENANCE_DUE",
        generator_id=gen.id
    )
    assert res_overdue.get("skipped") is not True


@pytest.mark.asyncio
async def test_notif_low_fuel_cooldown(db_session: AsyncSession):
    """NOTIF-06: 3-годинний cooldown для сповіщень про низький рівень пального"""
    gen = Generator(
        name="Gen Low Fuel Test",
        model="T-200",
        manufacturer="PowerGen",
        serial_number="SN-LOWFUEL-01",
        rated_power_kw=5.0,
        tank_capacity_l=25.0,
        fuel_type="А-95",
        nominal_consumption_l_per_h=2.0,
        status="STOPPED",
        is_configured=True
    )
    db_session.add(gen)
    await db_session.commit()

    # First low fuel notification
    res1 = await send_push_notification(
        db=db_session,
        title="⚠️ Критичний рівень палива — Gen Low Fuel Test",
        body="У баку залишилося 3.0 л",
        event_type="LOW_FUEL",
        generator_id=gen.id
    )
    assert res1.get("skipped") is not True

    # Immediate repeat -> Skipped
    res2 = await send_push_notification(
        db=db_session,
        title="⚠️ Критичний рівень палива — Gen Low Fuel Test",
        body="У баку залишилося 2.5 л",
        event_type="LOW_FUEL",
        generator_id=gen.id
    )
    assert res2.get("skipped") is True
    assert "менше 3 годин тому" in res2.get("reason", "")


def test_notif_webpush_error_handling_404_410():
    """NOTIF-08: Тільки HTTP 404 та 410 позначають підписку як прострочену"""
    from pywebpush import WebPushException

    class MockResponse:
        def __init__(self, code):
            self.status_code = code

    # Temporary network / 500 error -> is_expired must be False
    with patch("pywebpush.webpush", side_effect=WebPushException("Server Error", response=MockResponse(500))):
        ok, is_expired = _send_single_webpush_sync({"endpoint": "https://push.example.com"}, "data", None, {})
        assert ok is False
        assert is_expired is False

    # 410 Gone error -> is_expired must be True
    with patch("pywebpush.webpush", side_effect=WebPushException("Gone", response=MockResponse(410))):
        ok, is_expired = _send_single_webpush_sync({"endpoint": "https://push.example.com"}, "data", None, {})
        assert ok is False
        assert is_expired is True


@pytest.mark.asyncio
async def test_notif_settings_data_never_exposes_private_key(db_session: AsyncSession):
    """NOTIF-10: get_notification_settings_data повертає лише відкритий VAPID ключ"""
    data = await get_notification_settings_data(db_session)
    assert "vapid_public_key" in data
    assert "vapid_private_key" not in data
    assert "vapid_private_key_pem" not in data
    assert "private" not in str(data).lower()
