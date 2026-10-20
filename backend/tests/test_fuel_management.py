import pytest


@pytest.mark.asyncio
async def test_fuel_receipt_and_transfer_invariants(client, superadmin_auth, operator_auth):
    # Setup generator with 25L tank and 0L initial fuel
    await client.post(
        "/api/v1/generator/wizard",
        headers=superadmin_auth,
        json={
            "name": "Генератор паливний",
            "model": "PG-500",
            "manufacturer": "PG",
            "serial_number": "SN-FUEL-01",
            "rated_power_kw": 5.0,
            "tank_capacity_l": 25.0,
            "fuel_type": "А-95",
            "nominal_consumption_l_per_h": 2.0,
            "initial_operating_hours": 0.0,
            "initial_fuel_tank_level_l": 0.0,
            "work_schedule_start": "00:00",
            "work_schedule_end": "23:59",
            "maintenance_interval_hours": 300.0,
            "timezone": "Europe/Kyiv"
        }
    )

    # 1. Add fuel receipt to warehouse stock: 100 liters, 5800 грн (58 грн/л)
    rec_res = await client.post(
        "/api/v1/fuel/receipt",
        headers=operator_auth,
        json={
            "liters": 100.0,
            "cost_total": 5800.0,
            "fuel_type": "А-95",
            "driver_name": "Коваленко О.В.",
            "receipt_number": "ЧЕК-789456",
            "comment": "Постачання палива"
        }
    )
    assert rec_res.status_code == 201
    rec_data = rec_res.json()
    assert rec_data["liters"] == 100.0
    assert rec_data["cost_total"] == 5800.0
    assert rec_data["price_per_liter"] == 58.0
    assert rec_data["driver_name"] == "Коваленко О.В."

    # Check warehouse balance
    stock_res = await client.get("/api/v1/fuel/stock", headers=operator_auth)
    assert stock_res.status_code == 200
    assert stock_res.json()["current_balance_l"] == 100.0

    # 2. Invariant: cannot transfer more than stock balance
    over_transfer = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"liters": 150.0}
    )
    assert over_transfer.status_code == 400
    assert "Недостатньо палива на складі ГСМ" in over_transfer.json()["detail"]

    # 3. Invariant: cannot exceed tank capacity (tank capacity = 25L)
    over_capacity = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"liters": 30.0}
    )
    assert over_capacity.status_code == 400
    assert "Перевищення місткості бака" in over_capacity.json()["detail"]

    # 4. Valid transfer: 20 liters into tank
    valid_transfer = await client.post(
        "/api/v1/fuel/transfer",
        headers=operator_auth,
        json={"liters": 20.0, "comment": "Заправка перед робочою зміною"}
    )
    assert valid_transfer.status_code == 201
    t_data = valid_transfer.json()
    assert t_data["liters"] == 20.0
    assert t_data["source_balance_before"] == 100.0
    assert t_data["source_balance_after"] == 80.0
    assert t_data["tank_balance_before"] == 0.0
    assert t_data["tank_balance_after"] == 20.0

    # Verify summary endpoint
    summary_res = await client.get("/api/v1/fuel/summary", headers=operator_auth)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["warehouse_balance_l"] == 80.0
    assert summary["tank_balance_l"] == 20.0
    assert summary["total_received_l"] == 100.0
    assert summary["total_spent_uah"] == 5800.0
    assert summary["avg_price_per_liter"] == 58.0
    assert summary["total_transferred_l"] == 20.0


@pytest.mark.asyncio
async def test_fuel_stock_update_and_delete(client, superadmin_auth, operator_auth):
    # Get facility and initial stocks
    facs_res = await client.get('/api/v1/facilities', headers=superadmin_auth)
    assert facs_res.status_code == 200
    fac_id = facs_res.json()[0]['id']

    stocks_res = await client.get(f'/api/v1/fuel/stocks?facility_id={fac_id}', headers=operator_auth)
    assert stocks_res.status_code == 200
    stocks = stocks_res.json()
    assert len(stocks) >= 1
    stock1 = stocks[0]
    stock1_id = stock1['id']

    # Invariant: Operator CANNOT modify fuel stocks (403 Forbidden)
    op_upd = await client.put(
        f'/api/v1/fuel/stocks/{stock1_id}',
        headers=operator_auth,
        json={'name': 'Спроба оператора', 'fuel_type': 'А-95'}
    )
    assert op_upd.status_code == 403

    op_post = await client.post(
        '/api/v1/fuel/stocks',
        headers=operator_auth,
        json={'facility_id': fac_id, 'name': 'Склад', 'fuel_type': 'А-95'}
    )
    assert op_post.status_code == 403

    # 1. Admin/SuperAdmin updates stock
    upd_res = await client.put(
        f'/api/v1/fuel/stocks/{stock1_id}',
        headers=superadmin_auth,
        json={'name': 'Оновлений Склад 1', 'fuel_type': 'А-95 Mustang'}
    )
    assert upd_res.status_code == 200
    assert upd_res.json()['name'] == 'Оновлений Склад 1'
    assert upd_res.json()['fuel_type'] == 'А-95 Mustang'

    # 2. Cannot delete single warehouse on facility
    if len(stocks) == 1:
        del_fail = await client.delete(f'/api/v1/fuel/stocks/{stock1_id}', headers=superadmin_auth)
        assert del_fail.status_code == 400
        assert 'єдиний склад' in del_fail.json()['detail']

    # 3. Create second stock
    stock2_res = await client.post(
        '/api/v1/fuel/stocks',
        headers=superadmin_auth,
        json={
            'facility_id': fac_id,
            'name': 'Резервний склад 2',
            'fuel_type': 'А-95 Mustang',
            'initial_balance_l': 50.0
        }
    )
    assert stock2_res.status_code == 201
    stock2 = stock2_res.json()
    stock2_id = stock2['id']
    assert stock2['current_balance_l'] == 50.0

    # Delete stock2
    del_res = await client.delete(f'/api/v1/fuel/stocks/{stock2_id}', headers=superadmin_auth)
    assert del_res.status_code == 200
    assert 'успішно видалено' in del_res.json()['detail']

    # Verify remaining stocks: stock2 no longer exists
    stocks_after = (await client.get(f'/api/v1/fuel/stocks?facility_id={fac_id}', headers=operator_auth)).json()
    assert not any(s['id'] == stock2_id for s in stocks_after)

    # Check audit log for stock actions
    audit_res = await client.get('/api/v1/audit?limit=20', headers=superadmin_auth)
    assert audit_res.status_code == 200
    audit_actions = [a['action'] for a in audit_res.json()]
    assert 'FUEL_STOCK_UPDATED' in audit_actions
    assert 'FUEL_STOCK_DELETED' in audit_actions
