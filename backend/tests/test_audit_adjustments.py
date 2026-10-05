import pytest


@pytest.mark.asyncio
async def test_system_adjustments_and_audit(client, superadmin_auth, operator_auth):
    # Setup generator
    gen_res = await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор Аудиту",
            "model": "A-1",
            "manufacturer": "PG",
            "serial_number": "SN-AUDIT-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 50.0,
            "initial_fuel_tank_level_l": 10.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )
    assert gen_res.status_code == 200
    gen_id = gen_res.json()["id"]

    # 1. Operator attempts system adjustment -> FORBIDDEN (403)
    op_adj = await client.post(
        "/api/v1/adjustments",
        headers=operator_auth,
        json={
            "entity_type": "Generator",
            "entity_id": gen_id,
            "field_name": "current_operating_hours",
            "new_value": "45.0",
            "reason": "Спроба оператора зменшити лічильник"
        }
    )
    assert op_adj.status_code == 403
    assert "виключно головному системному адміністратору" in op_adj.json()["detail"]

    # 2. SuperAdmin attempts adjustment without valid reason -> BAD REQUEST (400 or 422)
    no_reason = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "Generator",
            "entity_id": gen_id,
            "field_name": "current_operating_hours",
            "new_value": "55.0",
            "reason": " "
        }
    )
    assert no_reason.status_code in (400, 422)

    # 3. SuperAdmin performs valid adjustment of operating hours
    valid_adj = await client.post(
        "/api/v1/adjustments",
        headers=superadmin_auth,
        json={
            "entity_type": "Generator",
            "entity_id": gen_id,
            "field_name": "current_operating_hours",
            "new_value": "55.0",
            "reason": "Коригування за актом звірки механічного лічильника №14"
        }
    )
    assert valid_adj.status_code == 201
    adj_data = valid_adj.json()
    assert adj_data["old_value"] == "50.0"
    assert adj_data["new_value"] == "55.0"
    assert "№14" in adj_data["reason"]

    # Verify generator current hours updated
    gen_check = await client.get("/api/v1/generator", headers=superadmin_auth)
    assert gen_check.json()["current_operating_hours"] == 55.0

    # 4. Check audit log contains both adjustments and previous operations
    audit_res = await client.get("/api/v1/audit", headers=superadmin_auth)
    assert audit_res.status_code == 200
    logs = audit_res.json()
    assert len(logs) > 0
    actions = [l["action"] for l in logs]
    assert "SYSTEM_ADJUSTMENT" in actions
    assert "GENERATOR_WIZARD_CONFIGURED" in actions
