# -*- coding: utf-8 -*-
import datetime
import pytest
from httpx import AsyncClient

from backend.app.services.fuel_service import normalize_fuel_family
from backend.app.services.report_service import format_audit_details_ua


def test_normalize_fuel_family():
    # A-95 variants and brands
    assert normalize_fuel_family("А-95 (WOG 95 Євро5-E10)") == "a95"
    assert normalize_fuel_family("OKKO Pulls 95") == "a95"
    assert normalize_fuel_family("А-95 Mustang (WOG 95 Mustang)") == "a95"
    assert normalize_fuel_family("А-95") == "a95"
    assert normalize_fuel_family("Бензин А-95") == "a95"
    assert normalize_fuel_family("a95") == "a95"

    # DP / Diesel variants and brands
    assert normalize_fuel_family("ДП (WOG ДП Євро5)") == "dp"
    assert normalize_fuel_family("WOG ДП Mustang+") == "dp"
    assert normalize_fuel_family("OKKO Pulls Diesel") == "dp"
    assert normalize_fuel_family("Дизельне паливо (ДП)") == "dp"
    assert normalize_fuel_family("ДТ") == "dp"
    assert normalize_fuel_family("diesel") == "dp"

    # A-92 and Gas
    assert normalize_fuel_family("А-92") == "a92"
    assert normalize_fuel_family("ГАЗ (WOG LPG)") == "gas"
    assert normalize_fuel_family("Газ (LPG)") == "gas"


def test_audit_details_ua_formatting():
    # 1. System updates (updates dict)
    details_updates = {
        "updates": {
            "organization_name": "Епіцентр Експрес Самар",
            "enforce_work_schedule": True,
            "work_schedule_start": "07:30",
            "work_schedule_end": "20:15",
            "default_maintenance_interval_hours": 300,
        }
    }
    formatted_updates = format_audit_details_ua(details_updates, "SETTINGS_UPDATE")
    assert "Організація: 'Епіцентр Експрес Самар'" in formatted_updates
    assert "Контроль графіка: увімкнено" in formatted_updates
    assert "Початок зміни: '07:30'" in formatted_updates
    assert "Кінець зміни: '20:15'" in formatted_updates
    assert "Інтервал ТО: 300" in formatted_updates

    # 2. Facility deletion (cascade and counts)
    details_del = {
        "name": "Х216, Гетьманська",
        "cascade": True,
        "generators_deleted": [],
        "fuel_stocks_deleted": ["Склад ГСМ (Х216, Гетьманська)"],
        "users_unbound_count": 1,
    }
    formatted_del = format_audit_details_ua(details_del, "FACILITY_DELETED")
    assert "Видалено об'єкт 'Х216, Гетьманська'" in formatted_del
    assert "видалено складів ГСМ: 1" in formatted_del
    assert "відкріплено користувачів: 1" in formatted_del

    # 3. Object changes diff
    details_changes = {
        "changes": {
            "name": {"old": "VULKAN I POWER", "new": "VULKAN"},
            "serial_number": {"old": "1234567890", "new": "б/н"},
        }
    }
    formatted_changes = format_audit_details_ua(details_changes, "GENERATOR_UPDATED")
    assert "Змінено параметри генератора:" in formatted_changes
    assert "Назва: 'VULKAN I POWER' ➔ 'VULKAN'" in formatted_changes
    assert "Серійний номер: '1234567890' ➔ 'б/н'" in formatted_changes


@pytest.mark.asyncio
async def test_generator_cooldown_flow(client: AsyncClient, superadmin_auth: dict):
    # 1. Create a test facility
    fac_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={"name": "Об'єкт Кулдаун", "address": "Вул. Тестова 10"}
    )
    assert fac_res.status_code == 201
    fac_id = fac_res.json()["id"]

    # 2. Create generator
    gen_payload = {
        "facility_id": fac_id,
        "name": "Генератор Кулдаун Тест",
        "model": "K&S KSB 6500",
        "manufacturer": "K&S",
        "serial_number": f"SN-COOL-{datetime.datetime.now().timestamp()}",
        "rated_power_kw": 5.5,
        "tank_capacity_l": 50.0,
        "fuel_type": "А-95",
        "nominal_consumption_l_per_h": 2.0,
        "initial_operating_hours": 10.0,
        "initial_fuel_tank_level_l": 30.0,
        "work_schedule_start": "00:00",
        "work_schedule_end": "23:59",
        "maintenance_interval_hours": 300.0,
        "timezone": "Europe/Kyiv"
    }
    gen_res = await client.post("/api/v1/generator", headers=superadmin_auth, json=gen_payload)
    assert gen_res.status_code == 201
    gen_id = gen_res.json()["id"]

    # Check cooldown initially is 0
    gen_check = await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=superadmin_auth)
    assert gen_check.status_code == 200
    assert gen_check.json().get("cooldown_remaining_seconds", 0) == 0

    # 3. Start generator
    start_res = await client.post(
        "/api/v1/generator/start",
        headers=superadmin_auth,
        json={"generator_id": gen_id, "operator_name": "Оператор Тест"}
    )
    assert start_res.status_code == 200

    # 4. Stop generator
    stop_res = await client.post(
        "/api/v1/generator/stop",
        headers=superadmin_auth,
        json={"generator_id": gen_id, "operator_name": "Оператор Тест"}
    )
    assert stop_res.status_code == 200

    # 5. Check cooldown remaining is now > 0 and <= 60
    gen_check2 = await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=superadmin_auth)
    assert gen_check2.status_code == 200
    cooldown = gen_check2.json().get("cooldown_remaining_seconds", 0)
    assert 0 < cooldown <= 60

    # 6. Immediate start without skip_cooldown MUST fail with 400
    failed_start = await client.post(
        "/api/v1/generator/start",
        headers=superadmin_auth,
        json={"generator_id": gen_id, "operator_name": "Оператор Тест"}
    )
    assert failed_start.status_code == 400
    assert "Захист від випадкового/передчасного запуску" in failed_start.json()["detail"]

    # 7. Start with skip_cooldown=True MUST succeed
    ok_start = await client.post(
        "/api/v1/generator/start",
        headers=superadmin_auth,
        json={"generator_id": gen_id, "operator_name": "Оператор Тест", "skip_cooldown": True}
    )
    assert ok_start.status_code == 200

    # Clean up: stop generator
    await client.post(
        "/api/v1/generator/stop",
        headers=superadmin_auth,
        json={"generator_id": gen_id, "operator_name": "Оператор Тест"}
    )


@pytest.mark.asyncio
async def test_fuel_generic_stock_and_cross_brand(client: AsyncClient, superadmin_auth: dict):
    # 1. Create Facility
    fac_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={"name": "Об'єкт Паливо Крос-Бренд"}
    )
    fac_id = fac_res.json()["id"]

    # 2. Add generic A-95 stock
    stock_res = await client.post(
        "/api/v1/fuel/stocks",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "name": "Основний склад ГСМ (А-95)",
            "fuel_type": "Бензин А-95",
            "initial_balance_l": 0.0,
        }
    )
    assert stock_res.status_code == 201
    stock_id = stock_res.json()["id"]

    # 3. Create Generator running on "А-95"
    gen_payload = {
        "facility_id": fac_id,
        "name": "Генератор А-95",
        "model": "K&S KSB 6500",
        "manufacturer": "K&S",
        "serial_number": f"SN-FUEL-{datetime.datetime.now().timestamp()}",
        "rated_power_kw": 5.5,
        "tank_capacity_l": 50.0,
        "fuel_type": "А-95",
        "nominal_consumption_l_per_h": 2.0,
        "initial_operating_hours": 10.0,
        "initial_fuel_tank_level_l": 10.0,
        "work_schedule_start": "00:00",
        "work_schedule_end": "23:59",
        "maintenance_interval_hours": 300.0,
        "timezone": "Europe/Kyiv"
    }
    gen_res = await client.post("/api/v1/generator", headers=superadmin_auth, json=gen_payload)
    assert gen_res.status_code == 201
    gen_id = gen_res.json()["id"]

    # 4. Receive "OKKO Pulls 95" receipt into generic "Бензин А-95" stock
    rec_res = await client.post(
        "/api/v1/fuel/receipt",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "fuel_type": "OKKO Pulls 95",
            "liters": 60.0,
            "cost_total": 3600.0,
            "driver_name": "Водій Тест",
            "receipt_number": "ЧЕК-OKKO-999"
        }
    )
    assert rec_res.status_code == 201

    # Check stock balance is 60.0 L
    stocks_res = await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)
    assert stocks_res.status_code == 200
    found_stock = next(s for s in stocks_res.json() if s["id"] == stock_id)
    assert found_stock["current_balance_l"] == 60.0

    # 5. Transfer 20.0 L from generic stock to generator tank
    transfer_res = await client.post(
        "/api/v1/fuel/transfer",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "generator_id": gen_id,
            "liters": 20.0,
            "comment": "Заправка бака"
        }
    )
    assert transfer_res.status_code == 201, transfer_res.text

    # Check stock balance is 40.0 L and generator tank is 30.0 L (10 initial + 20)
    stocks_res2 = await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)
    found_stock2 = next(s for s in stocks_res2.json() if s["id"] == stock_id)
    assert found_stock2["current_balance_l"] == 40.0

    gen_check = await client.get(f"/api/v1/generator?generator_id={gen_id}", headers=superadmin_auth)
    assert gen_check.json()["fuel_tank_level_l"] == 30.0


@pytest.mark.asyncio
async def test_excel_daily_report_chronological_sequence(client: AsyncClient, superadmin_auth: dict):
    import io
    import openpyxl

    # 1. Create Facility
    fac_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={"name": "Об'єкт Excel Хронологія", "timezone": "Europe/Kyiv"}
    )
    fac_id = fac_res.json()["id"]

    # 2. Create Generator
    gen_payload = {
        "facility_id": fac_id,
        "name": "Генератор Календар",
        "model": "K&S KSB 6500",
        "manufacturer": "K&S",
        "serial_number": f"SN-CAL-{datetime.datetime.now().timestamp()}",
        "rated_power_kw": 5.5,
        "tank_capacity_l": 50.0,
        "fuel_type": "А-95",
        "nominal_consumption_l_per_h": 2.0,
        "initial_operating_hours": 100.0,
        "initial_fuel_tank_level_l": 20.0,
        "work_schedule_start": "00:00",
        "work_schedule_end": "23:59",
        "maintenance_interval_hours": 300.0,
        "timezone": "Europe/Kyiv"
    }
    gen_res = await client.post("/api/v1/generator", headers=superadmin_auth, json=gen_payload)
    gen_id = gen_res.json()["id"]

    # 3. Request Excel report for date range 2026-11-01 to 2026-11-05 (5 days)
    # Even without runs, standard calendar range should contain all 5 days in exact order
    res = await client.get(
        f"/api/v1/reports/export-excel?generator_id={gen_id}&start_date=2026-11-01&end_date=2026-11-05",
        headers=superadmin_auth
    )
    assert res.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    ws2 = wb["Звіт по днях"]

    dates_in_col_b = []
    for row in range(2, ws2.max_row + 1):
        val = ws2.cell(row=row, column=2).value
        status = ws2.cell(row=row, column=15).value
        note = ws2.cell(row=row, column=16).value
        if val and val != "РАЗОМ":
            dates_in_col_b.append((str(val), str(status or ""), str(note or "")))

    expected_dates = ["01.11.2026", "02.11.2026", "03.11.2026", "04.11.2026", "05.11.2026"]
    actual_dates = [d[0] for d in dates_in_col_b]

    # Check exact chronological sequence without any shifting or backwards dates
    assert actual_dates == expected_dates
    # Check that idle days are marked appropriately
    for d, st, nt in dates_in_col_b:
        assert "Черговий режим (без запусків)" in st
        assert "Генератор не запускався" in nt

