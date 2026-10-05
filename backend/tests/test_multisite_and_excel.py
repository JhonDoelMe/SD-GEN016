import io
import pytest
import openpyxl


@pytest.mark.asyncio
async def test_facility_crud_and_multisite(client, superadmin_auth, operator_auth):
    # 1. List facilities - default facility should exist
    fac_list_res = await client.get("/api/v1/facilities", headers=superadmin_auth)
    assert fac_list_res.status_code == 200
    facs = fac_list_res.json()
    assert len(facs) >= 1
    default_fac = facs[0]
    assert "Основний об'єкт" in default_fac["name"]

    # 2. Create second facility
    create_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={
            "name": "Філія №2 (Дарниця)",
            "address": "вул. Бориспільська, 9",
            "description": "Резервний вузол зв'язку",
            "timezone": "Europe/Kyiv"
        }
    )
    assert create_res.status_code == 201
    new_fac = create_res.json()
    assert new_fac["name"] == "Філія №2 (Дарниця)"
    assert new_fac["id"] > default_fac["id"]

    # 3. Update facility
    update_res = await client.put(
        f"/api/v1/facilities/{new_fac['id']}",
        headers=superadmin_auth,
        json={"address": "вул. Бориспільська, 15"}
    )
    assert update_res.status_code == 200
    assert update_res.json()["address"] == "вул. Бориспільська, 15"

    # 4. Check fuel stock auto-created for this facility
    stock_res = await client.get(
        f"/api/v1/fuel/stock?facility_id={new_fac['id']}",
        headers=superadmin_auth
    )
    assert stock_res.status_code == 200

    # 5. Delete facility
    del_res = await client.delete(
        f"/api/v1/facilities/{new_fac['id']}",
        headers=superadmin_auth
    )
    assert del_res.status_code == 200
    assert "успішно видалено" in del_res.json()["message"]


@pytest.mark.asyncio
async def test_generator_creation_deletion_and_safety(client, superadmin_auth, operator_auth):
    # 1. Create a new generator
    gen_create_res = await client.post(
        "/api/v1/generator",
        headers=superadmin_auth,
        json={
            "facility_id": 1,
            "name": "Тестовий генератор 7кВт",
            "model": "Honda EM 6500",
            "manufacturer": "Honda",
            "serial_number": "HND-778899",
            "rated_power_kw": 7.0,
            "tank_capacity_l": 30.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.5,
            "initial_operating_hours": 10.0,
            "initial_fuel_tank_level_l": 20.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )
    assert gen_create_res.status_code == 201
    new_gen = gen_create_res.json()
    gen_id = new_gen["id"]

    # 2. Start the generator
    start_res = await client.post(
        "/api/v1/generator/start",
        headers=operator_auth,
        json={"generator_id": gen_id, "fuel_level_l": 20.0}
    )
    assert start_res.status_code == 200

    # 3. Safety check: Invariant - cannot delete RUNNING generator
    del_running_res = await client.delete(
        f"/api/v1/generator/{gen_id}",
        headers=superadmin_auth
    )
    assert del_running_res.status_code == 400
    assert "зараз працює" in del_running_res.json()["detail"]

    # 4. Stop the generator
    stop_res = await client.post(
        "/api/v1/generator/stop",
        headers=operator_auth,
        json={"generator_id": gen_id, "note": "Зупинка перед видаленням"}
    )
    assert stop_res.status_code == 200

    # 5. Delete stopped generator -> success
    del_ok_res = await client.delete(
        f"/api/v1/generator/{gen_id}",
        headers=superadmin_auth
    )
    assert del_ok_res.status_code == 200
    assert "успішно видалено" in del_ok_res.json()["message"]


@pytest.mark.asyncio
async def test_maintenance_schedule_calculation_and_recalculate(client, superadmin_auth):
    # Setup generator with current hours = 235.0, interval = 300.0
    setup_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор ТО Тест",
            "model": "GT-5000",
            "manufacturer": "GenTech",
            "serial_number": "SN-TO-300",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.2,
            "initial_operating_hours": 235.0,
            "initial_fuel_tank_level_l": 15.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )
    assert setup_res.status_code == 200
    gen_id = setup_res.json()["id"]

    # Check maintenance schedule status: next_due should be 300.0, remaining should be 65.0
    sched_res = await client.get(
        f"/api/v1/maintenance/schedule?generator_id={gen_id}",
        headers=superadmin_auth
    )
    assert sched_res.status_code == 200
    sched = sched_res.json()
    assert sched["interval_hours"] == 300.0
    assert sched["next_due_hours"] == 300.0
    assert sched["hours_remaining"] == 65.0

    # Test recalculate endpoint
    recalc_res = await client.post(
        f"/api/v1/maintenance/schedule/recalculate?generator_id={gen_id}",
        headers=superadmin_auth
    )
    assert recalc_res.status_code == 200
    recalc = recalc_res.json()
    assert recalc["next_due_hours"] == 300.0
    assert recalc["hours_remaining"] == 65.0


@pytest.mark.asyncio
async def test_dynamic_excel_report_generation(client, superadmin_auth):
    # Request Excel report
    res = await client.get("/api/v1/reports/export-excel", headers=superadmin_auth)
    assert res.status_code == 200
    assert "spreadsheetml.sheet" in res.headers["content-type"]
    assert "attachment; filename=" in res.headers["content-disposition"]
    assert len(res.content) > 1000

    # Parse Excel with openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    sheet_names = wb.sheetnames

    # Verify all 5 required sheets exist
    assert "Загальний звіт" in sheet_names
    assert "Звіт по днях" in sheet_names
    assert "Рух палива та Склад ГСМ" in sheet_names
    assert "Технічне обслуговування" in sheet_names
    assert "Журнал інцидентів та дій" in sheet_names

    # Verify Sheet 1 content
    ws1 = wb["Загальний звіт"]
    assert "SERVICE DESK" in ws1["A1"].value

    # Verify Sheet 2 freeze panes and headers
    ws2 = wb["Звіт по днях"]
    assert ws2.freeze_panes == "A2"
    assert ws2["A1"].value == "№"
    assert ws2["B1"].value == "Дата (РРРР-ММ-ДД)"


@pytest.mark.asyncio
async def test_multi_warehouse_receipt_transfer_and_excel(client, superadmin_auth):
    # 1. Create a facility
    fac_res = await client.post("/api/v1/facilities", json={
        "name": "Локація Захід (Львів)",
        "address": "вул. Городоцька, 15",
        "description": "Тестова локація",
        "timezone": "Europe/Kyiv"
    }, headers=superadmin_auth)
    assert fac_res.status_code == 201
    fac_id = fac_res.json()["id"]

    # 2. Create a generator for this facility
    gen_res = await client.post("/api/v1/generator", json={
        "facility_id": fac_id,
        "name": "Генератор Львів-1",
        "model": "Kipor KDE6700",
        "manufacturer": "Kipor",
        "serial_number": "LV-6700-01",
        "rated_power_kw": 5.5,
        "tank_capacity_l": 25.0,
        "fuel_type": "А-95",
        "nominal_consumption_l_per_h": 1.4,
        "initial_operating_hours": 10.0,
        "initial_fuel_tank_level_l": 5.0,
        "maintenance_interval_hours": 300.0,
        "work_schedule_start": "08:00",
        "work_schedule_end": "20:00",
        "timezone": "Europe/Kyiv"
    }, headers=superadmin_auth)
    assert gen_res.status_code == 201
    gen_id = gen_res.json()["id"]

    # 3. Create a fuel warehouse for this facility
    stock_res = await client.post("/api/v1/fuel/stock/new", json={
        "facility_id": fac_id,
        "name": "Резервний склад Львів",
        "fuel_type": "А-95",
        "initial_balance_l": 50.0
    }, headers=superadmin_auth)
    assert stock_res.status_code == 201
    stock = stock_res.json()
    stock_id = stock["id"]
    assert stock["name"] == "Резервний склад Львів"
    assert stock["current_balance_l"] == 50.0

    # 4. List stocks for this facility
    list_res = await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)
    assert list_res.status_code == 200
    stocks = list_res.json()
    assert any(s["id"] == stock_id for s in stocks)

    # 5. Add fuel receipt directly to this warehouse
    rec_res = await client.post("/api/v1/fuel/receipt", json={
        "facility_id": fac_id,
        "stock_id": stock_id,
        "liters": 100.0,
        "cost_total": 5600.0,
        "driver_name": "Петренко П.П.",
        "receipt_number": "ЧЕК-LV-100",
        "fuel_type": "А-95",
        "comment": "Завіз палива"
    }, headers=superadmin_auth)
    assert rec_res.status_code == 201
    rec = rec_res.json()
    assert rec["stock_name"] == "Резервний склад Львів"
    assert rec["liters"] == 100.0
    assert rec["facility_name"] == "Локація Захід (Львів)"

    # 6. Transfer fuel to generator tank
    trans_res = await client.post("/api/v1/fuel/transfer", json={
        "facility_id": fac_id,
        "stock_id": stock_id,
        "generator_id": gen_id,
        "liters": 15.0,
        "comment": "Заправка перед роботою"
    }, headers=superadmin_auth)
    assert trans_res.status_code == 201
    trans = trans_res.json()
    assert trans["stock_name"] == "Резервний склад Львів"
    assert trans["generator_name"] == "Генератор Львів-1"
    assert trans["liters"] == 15.0
    assert trans["tank_balance_after"] == 20.0

    # 7. Generate Excel report for this facility
    rep_res = await client.get(f"/api/v1/reports/export-excel?facility_id={fac_id}", headers=superadmin_auth)
    assert rep_res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(rep_res.content))
    ws_fuel = wb["Рух палива та Склад ГСМ"]
    # Check that receipt and transfer data appear in the worksheet
    sheet_text = " ".join(str(cell.value) for row in ws_fuel.iter_rows() for cell in row if cell.value)
    assert "Резервний склад Львів" in sheet_text
    assert "ЧЕК-LV-100" in sheet_text

