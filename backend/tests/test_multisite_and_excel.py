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
