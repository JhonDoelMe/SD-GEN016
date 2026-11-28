import json
import pytest
from sqlalchemy import select

from backend.app.models.audit import AuditLog
from backend.app.models.fuel import FuelStock


@pytest.mark.asyncio
async def test_negative_tank_auto_zero_deficit_audit_and_monthly_avg(client, superadmin_auth, db_session):
    """
    Перевіряє нову логіку обліку дефіциту та середньої фактичної витрати за місяць:
    1) Зупинка при розрахунковому мінусі в баку НЕ блокується: бак обнуляється до 0 л,
       у цикл/звіт іде лише реально списане з бака, а надлишок іде виключно в аудит і monthly_deficit_l.
    2) Пуск і зупинка з 0 л у баку дозволені: у звіті 0.0 -> 0.0 л (0.0 л списано),
       дефіцит додається в аудит і monthly_deficit_l.
    3) Фактична середня витрата за місяць рахується по живому балансу бака (спалене з бака / відпрацьовані години),
       не включаючи паливо, яке просто лежить на складі ПММ.
    """
    wiz = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Дефіцит Тест",
            "model": "Def-5000",
            "manufacturer": "Test",
            "serial_number": "SN-DEF-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 40.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 3.0,
            "initial_operating_hours": 100.0,
            "initial_fuel_tank_level_l": 6.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv",
        },
    )
    assert wiz.status_code == 200
    gen_id = wiz.json()["id"]
    fac_id = wiz.json()["facility_id"]

    # Add 100 L to warehouse stock — must NOT count as burned fuel!
    stock = (await db_session.execute(select(FuelStock).where(FuelStock.facility_id == fac_id))).scalars().first()
    if stock:
        stock.current_balance_l = 100.0
        await db_session.commit()

    # Run 1: tank has 6.0 L, runs 5.0h (theoretical 15.0 L -> -9.0 L shortage)
    assert (await client.post("/api/v1/generator/start", headers=superadmin_auth, json={"generator_id": gen_id, "skip_cooldown": True})).status_code == 200
    stop1 = await client.post(
        "/api/v1/generator/stop",
        headers=superadmin_auth,
        json={"generator_id": gen_id, "end_hours": 105.0, "force_confirm": True},
    )
    assert stop1.status_code == 200
    r1 = stop1.json()
    assert r1["start_fuel_level_l"] == 6.0
    assert r1["end_fuel_level_l"] == 0.0
    assert r1["calculated_consumption_l"] == 6.0  # Only what was on record in tank

    # Run 2: starts with 0.0 L, runs 1.0h (theoretical 3.0 L -> 3.0 L shortage)
    assert (await client.post("/api/v1/generator/start", headers=superadmin_auth, json={"generator_id": gen_id, "skip_cooldown": True})).status_code == 200
    stop2 = await client.post(
        "/api/v1/generator/stop",
        headers=superadmin_auth,
        json={"generator_id": gen_id, "end_hours": 106.0, "force_confirm": True},
    )
    assert stop2.status_code == 200
    r2 = stop2.json()
    assert r2["start_fuel_level_l"] == 0.0
    assert r2["end_fuel_level_l"] == 0.0
    assert r2["calculated_consumption_l"] == 0.0  # Start & stop with empty tank

    # Verify AuditLog has 2 GENERATOR_FUEL_DEFICIT entries totaling 9.0 + 3.0 = 12.0 L
    deficits = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "GENERATOR_FUEL_DEFICIT",
                AuditLog.entity_id == str(gen_id),
            )
        )
    ).scalars().all()
    assert len(deficits) == 2
    shortage_sum = sum(float(json.loads(d.details_json)["fuel_shortage_l"]) for d in deficits)
    assert round(shortage_sum, 2) == 12.0

    # Verify /fuel/summary shows monthly_deficit_l == 12.0 and live monthly avg = 6.0 L burned / 6.0h = 1.0 L/h
    fs = (await client.get(f"/api/v1/fuel/summary?facility_id={fac_id}&generator_id={gen_id}", headers=superadmin_auth)).json()
    assert fs["monthly_deficit_l"] == 12.0
    assert fs["monthly_burned_fuel_l"] == 6.0  # Warehouse 100 L NOT counted!
    assert fs["monthly_operating_hours"] == 6.0
    assert fs["monthly_avg_consumption_l_per_h"] == 1.0

    # Verify /reports/summary excludes deficit (total_calculated_consumption_l == 6.0) and exposes UI-only monthly actual avg
    rep = (await client.get(f"/api/v1/reports/summary?generator_id={gen_id}", headers=superadmin_auth)).json()
    assert rep["total_runs_count"] == 2
    assert rep["total_operating_hours"] == 6.0
    assert rep["total_calculated_consumption_l"] == 6.0
    assert rep["monthly_actual_avg_consumption_l_per_h"] == 1.0
    assert rep["monthly_actual_burned_fuel_l"] == 6.0
    assert rep["nominal_consumption_l_per_h"] == 3.0
