# -*- coding: utf-8 -*-
import asyncio
from decimal import Decimal
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_t01_multi_facility_stock_isolation(client: AsyncClient, superadmin_auth: dict):
    # 1. Create Facility 1
    fac1_res = await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт 1 Ізоляція'})
    assert fac1_res.status_code == 201
    fac1_id = fac1_res.json()['id']

    # 2. Create Facility 2
    fac2_res = await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт 2 Ізоляція'})
    assert fac2_res.status_code == 201
    fac2_id = fac2_res.json()['id']

    # 3. Add receipt to Facility 1: 100L
    rec1 = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={
            'facility_id': fac1_id,
            'fuel_type': 'А-95',
            'liters': 100.0,
            'cost_total': 5800.0,
            'driver_name': 'Водій 1',
            'receipt_number': 'ЧЕК-ISO-1'
        }
    )
    assert rec1.status_code == 201

    # 4. Query stocks for Facility 2 — must NOT see Facility 1 stock!
    stocks2_res = await client.get(f'/api/v1/fuel/stocks?facility_id={fac2_id}', headers=superadmin_auth)
    assert stocks2_res.status_code == 200
    stocks2 = stocks2_res.json()
    assert len(stocks2) >= 1
    for s in stocks2:
        assert s['facility_id'] == fac2_id
        assert s['current_balance_l'] == 0.0

    # Facility 1 stock retains 100L
    stocks1_res = await client.get(f'/api/v1/fuel/stocks?facility_id={fac1_id}', headers=superadmin_auth)
    assert stocks1_res.status_code == 200
    assert stocks1_res.json()[0]['current_balance_l'] == 100.0


@pytest.mark.asyncio
async def test_t02_facility_without_stock_creates_own_stock(client: AsyncClient, superadmin_auth: dict):
    fac_res = await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Без Складу'})
    assert fac_res.status_code == 201
    fac_id = fac_res.json()['id']

    stock_res = await client.get(f'/api/v1/fuel/stock?facility_id={fac_id}', headers=superadmin_auth)
    assert stock_res.status_code == 200
    stock_data = stock_res.json()
    assert stock_data['facility_id'] == fac_id
    assert stock_data['current_balance_l'] == 0.0
    assert 'склад' in stock_data['name'].lower()


@pytest.mark.asyncio
async def test_t03_concurrent_fuel_transfer_prevention(client: AsyncClient, superadmin_auth: dict):
    # 1. Facility & Generator
    fac_res = await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Конкурентності'})
    fac_id = fac_res.json()['id']

    gen_res = await client.post(
        '/api/v1/generator',
        headers=superadmin_auth,
        json={
            'name': 'Генератор Конкурентний',
            'model': 'Mod-1',
            'manufacturer': 'Brand',
            'serial_number': 'SN-C01',
            'rated_power_kw': 5.0,
            'tank_capacity_l': 100.0,
            'fuel_type': 'А-95',
            'nominal_consumption_l_per_h': 2.2,
            'facility_id': fac_id
        }
    )
    assert gen_res.status_code == 201
    gen_id = gen_res.json()['id']

    # 2. Stock with exactly 50L
    rec = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={
            'facility_id': fac_id,
            'fuel_type': 'А-95',
            'liters': 50.0,
            'cost_total': 2900.0,
            'driver_name': 'Тестер',
            'receipt_number': 'ЧЕК-C01'
        }
    )
    assert rec.status_code == 201
    stock_id = rec.json()['stock_id']

    # 3. First transfer of 35L succeeds (50 -> 15)
    tr1 = await client.post(
        '/api/v1/fuel/transfer',
        headers=superadmin_auth,
        json={'facility_id': fac_id, 'stock_id': stock_id, 'generator_id': gen_id, 'liters': 35.0}
    )
    assert tr1.status_code == 201

    # 4. Second transfer of 35L must FAIL because only 15L is available
    tr2 = await client.post(
        '/api/v1/fuel/transfer',
        headers=superadmin_auth,
        json={'facility_id': fac_id, 'stock_id': stock_id, 'generator_id': gen_id, 'liters': 35.0}
    )
    assert tr2.status_code == 400
    assert 'Недостатньо палива на складі ГСМ' in tr2.json()['detail']

    # Final balance check: exactly 15.0L left (50 - 35), generator tank level exactly 35.0L
    st_check = await client.get(f'/api/v1/fuel/stocks?facility_id={fac_id}', headers=superadmin_auth)
    assert st_check.json()[0]['current_balance_l'] == 15.0


@pytest.mark.asyncio
async def test_t04_concurrent_receipt_safety(client: AsyncClient, superadmin_auth: dict):
    fac_res = await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Приходу'})
    fac_id = fac_res.json()['id']

    stock_res = await client.get(f'/api/v1/fuel/stock?facility_id={fac_id}', headers=superadmin_auth)
    stock_id = stock_res.json()['id']

    # Add 4 receipts of 20L = 80L
    for i in range(4):
        r = await client.post(
            '/api/v1/fuel/receipt',
            headers=superadmin_auth,
            json={
                'facility_id': fac_id,
                'stock_id': stock_id,
                'fuel_type': 'А-95',
                'liters': 20.0,
                'cost_total': 1160.0,
                'driver_name': f'Водій {i}',
                'receipt_number': f'ЧЕК-CONC-{i}'
            }
        )
        assert r.status_code == 201

    st_check = await client.get(f'/api/v1/fuel/stocks?facility_id={fac_id}', headers=superadmin_auth)
    assert st_check.json()[0]['current_balance_l'] == 80.0


@pytest.mark.asyncio
async def test_t05_idempotency_duplicate_protection(client: AsyncClient, superadmin_auth: dict):
    fac_res = await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Ідемпотентності'})
    fac_id = fac_res.json()['id']

    idemp_key = 'IDEMP-REC-TEST-999'
    payload = {
        'facility_id': fac_id,
        'fuel_type': 'А-95',
        'liters': 45.0,
        'cost_total': 2610.0,
        'driver_name': 'Ідемпотентний Водій',
        'receipt_number': 'ЧЕК-IDEMP-01',
        'idempotency_key': idemp_key
    }

    # First request
    res1 = await client.post('/api/v1/fuel/receipt', headers=superadmin_auth, json=payload)
    assert res1.status_code == 201
    rec1_data = res1.json()

    # Second duplicate request
    res2 = await client.post('/api/v1/fuel/receipt', headers=superadmin_auth, json=payload)
    assert res2.status_code in (200, 201)
    rec2_data = res2.json()

    assert rec1_data['id'] == rec2_data['id']

    # Balance must remain exactly 45.0L (NOT 90.0L)
    stocks = (await client.get(f'/api/v1/fuel/stocks?facility_id={fac_id}', headers=superadmin_auth)).json()
    assert stocks[0]['current_balance_l'] == 45.0


@pytest.mark.asyncio
async def test_t06_mismatched_facility_id_rejected(client: AsyncClient, superadmin_auth: dict):
    # Facility 1
    f1 = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт 1'})).json()['id']
    st1 = (await client.get(f'/api/v1/fuel/stock?facility_id={f1}', headers=superadmin_auth)).json()['id']

    # Facility 2
    f2 = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт 2'})).json()['id']

    # Attempt to add receipt specifying stock from Facility 1, but facility_id of Facility 2
    res = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={
            'facility_id': f2,
            'stock_id': st1,
            'fuel_type': 'А-95',
            'liters': 50.0,
            'cost_total': 2900.0,
            'driver_name': 'Тестер',
            'receipt_number': 'ЧЕК-MISMATCH'
        }
    )
    assert res.status_code == 400
    assert 'Невідповідність об\'єкт' in res.json()['detail']


@pytest.mark.asyncio
async def test_t07_fuel_type_mismatch_rejected(client: AsyncClient, superadmin_auth: dict):
    f = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Типів'})).json()['id']

    # Create generator requiring ДП (Diesel)
    gen = (await client.post(
        '/api/v1/generator',
        headers=superadmin_auth,
        json={
            'name': 'Дизельний Генератор',
            'model': 'D-100',
            'manufacturer': 'Brand',
            'serial_number': 'SN-DIESEL',
            'rated_power_kw': 5.0,
            'tank_capacity_l': 50.0,
            'fuel_type': 'ДП',
            'nominal_consumption_l_per_h': 2.2,
            'facility_id': f
        }
    )).json()['id']

    # Stock with A-95 gasoline (100L)
    rec = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={
            'facility_id': f,
            'fuel_type': 'А-95',
            'liters': 100.0,
            'cost_total': 5800.0,
            'driver_name': 'Тестер',
            'receipt_number': 'ЧЕК-А95'
        }
    )
    assert rec.status_code == 201
    st_id = rec.json()['stock_id']

    # 1. Attempt transfer A-95 to Diesel generator -> 400
    tr_res = await client.post(
        '/api/v1/fuel/transfer',
        headers=superadmin_auth,
        json={
            'facility_id': f,
            'stock_id': st_id,
            'generator_id': gen,
            'liters': 20.0
        }
    )
    assert tr_res.status_code == 400
    assert 'Несумісність типів палива' in tr_res.json()['detail']

    # 2. Attempt receipt of Diesel into non-empty A-95 stock -> 400
    rec_bad = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={
            'facility_id': f,
            'stock_id': st_id,
            'fuel_type': 'ДП',
            'liters': 50.0,
            'cost_total': 2750.0,
            'driver_name': 'Тестер',
            'receipt_number': 'ЧЕК-MIX'
        }
    )
    assert rec_bad.status_code == 400
    assert 'Невідповідність типу палива' in rec_bad.json()['detail']


@pytest.mark.asyncio
async def test_t08_default_fuel_provider_hierarchy(client: AsyncClient, superadmin_auth: dict):
    f = (await client.post(
        '/api/v1/facilities',
        headers=superadmin_auth,
        json={'name': 'Об\'єкт ОККО', 'default_fuel_provider': 'okko'}
    )).json()['id']

    # Receipt without explicit fuel_provider must inherit facility default 'okko'
    rec_res = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={
            'facility_id': f,
            'fuel_type': 'А-95',
            'liters': 20.0,
            'cost_total': 1160.0,
            'driver_name': 'Водій',
            'receipt_number': 'ЧЕК-DEF-OKKO'
        }
    )
    assert rec_res.status_code == 201
    assert rec_res.json()['fuel_provider'] == 'okko'


@pytest.mark.asyncio
async def test_t09_force_confirm_permission_check(client: AsyncClient, operator_auth: dict, superadmin_auth: dict):
    facs = (await client.get('/api/v1/facilities', headers=superadmin_auth)).json()
    f = facs[0]['id']

    # Anomaly payload: volume 1500L (> 1000L warning limit)
    over_payload = {
        'facility_id': f,
        'fuel_type': 'А-95',
        'liters': 1500.0,
        'cost_total': 87000.0,
        'driver_name': 'Бензовоз',
        'receipt_number': 'ЧЕК-БОЧКА',
        'force_confirm': True
    }

    # Operator (lacks fuel:receipt:override) -> 403 Forbidden
    op_res = await client.post('/api/v1/fuel/receipt', headers=operator_auth, json=over_payload)
    assert op_res.status_code == 403
    assert 'fuel:receipt:override' in op_res.json()['detail']

    # SuperAdmin (has override permission) -> 201 Created
    adm_res = await client.post('/api/v1/fuel/receipt', headers=superadmin_auth, json=over_payload)
    assert adm_res.status_code == 201
    assert adm_res.json()['liters'] == 1500.0


@pytest.mark.asyncio
async def test_t10_stock_archival_preserves_history(client: AsyncClient, superadmin_auth: dict):
    f = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Архіву'})).json()['id']

    st1_id = (await client.get(f'/api/v1/fuel/stock?facility_id={f}', headers=superadmin_auth)).json()['id']

    st2_res = await client.post(
        '/api/v1/fuel/stocks',
        headers=superadmin_auth,
        json={'facility_id': f, 'name': 'Склад Резерв', 'fuel_type': 'А-95'}
    )
    assert st2_res.status_code == 201
    st2_id = st2_res.json()['id']

    # Add receipt to Stock 1
    rec = (await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={
            'facility_id': f,
            'stock_id': st1_id,
            'fuel_type': 'А-95',
            'liters': 50.0,
            'cost_total': 2900.0,
            'driver_name': 'Водій',
            'receipt_number': 'ЧЕК-АРХ-1'
        }
    )).json()
    rec_id = rec['id']

    # Delete Stock 1 (transfers remaining 50L to Stock 2 and soft-archives Stock 1)
    del_res = await client.delete(f'/api/v1/fuel/stocks/{st1_id}', headers=superadmin_auth)
    assert del_res.status_code == 200

    # Verify receipt STILL references st1_id
    receipts = (await client.get(f'/api/v1/fuel/receipts?facility_id={f}', headers=superadmin_auth)).json()
    found_rec = next(r for r in receipts if r['id'] == rec_id)
    assert found_rec['stock_id'] == st1_id  # Historical stock_id preserved!


@pytest.mark.asyncio
async def test_t11_multi_stock_summary_aggregation(client: AsyncClient, superadmin_auth: dict):
    f = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Мультисклад'})).json()['id']

    # Stock 1: 40L
    rec1 = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={'facility_id': f, 'fuel_type': 'А-95', 'liters': 40.0, 'cost_total': 2320.0, 'driver_name': 'Водій', 'receipt_number': 'R1'}
    )
    assert rec1.status_code == 201

    # Stock 2: 60L
    await client.post(
        '/api/v1/fuel/stocks',
        headers=superadmin_auth,
        json={'facility_id': f, 'name': 'Склад 2', 'fuel_type': 'А-95', 'initial_balance_l': 60.0}
    )

    summary = (await client.get(f'/api/v1/fuel/summary?facility_id={f}', headers=superadmin_auth)).json()
    assert summary['warehouse_balance_l'] == 100.0  # 40 + 60


@pytest.mark.asyncio
async def test_t12_multi_generator_tank_summary(client: AsyncClient, superadmin_auth: dict):
    f = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Мультиген'})).json()['id']

    # Generator 1 (tank 25L)
    g1 = (await client.post(
        '/api/v1/generator',
        headers=superadmin_auth,
        json={
            'name': 'Ген 1',
            'model': 'M1',
            'manufacturer': 'Brand',
            'serial_number': 'SN-G1',
            'rated_power_kw': 5.0,
            'tank_capacity_l': 25.0,
            'fuel_type': 'А-95',
            'nominal_consumption_l_per_h': 2.2,
            'facility_id': f
        }
    )).json()['id']

    # Generator 2 (tank 50L)
    g2 = (await client.post(
        '/api/v1/generator',
        headers=superadmin_auth,
        json={
            'name': 'Ген 2',
            'model': 'M2',
            'manufacturer': 'Brand',
            'serial_number': 'SN-G2',
            'rated_power_kw': 7.5,
            'tank_capacity_l': 50.0,
            'fuel_type': 'А-95',
            'nominal_consumption_l_per_h': 2.8,
            'facility_id': f
        }
    )).json()['id']

    # Deposit fuel to warehouse: 100L
    rec = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={'facility_id': f, 'fuel_type': 'А-95', 'liters': 100.0, 'cost_total': 5800.0, 'driver_name': 'Водій', 'receipt_number': 'R-GEN'}
    )
    assert rec.status_code == 201
    st_id = rec.json()['stock_id']

    # Fuel Gen 1: 10L
    tr1 = await client.post(
        '/api/v1/fuel/transfer',
        headers=superadmin_auth,
        json={'facility_id': f, 'stock_id': st_id, 'generator_id': g1, 'liters': 10.0}
    )
    assert tr1.status_code == 201

    # Fuel Gen 2: 25L
    tr2 = await client.post(
        '/api/v1/fuel/transfer',
        headers=superadmin_auth,
        json={'facility_id': f, 'stock_id': st_id, 'generator_id': g2, 'liters': 25.0}
    )
    assert tr2.status_code == 201

    summary = (await client.get(f'/api/v1/fuel/summary?facility_id={f}', headers=superadmin_auth)).json()
    assert summary['tank_balance_l'] == 35.0  # 10 + 25
    assert summary['tank_capacity_l'] == 75.0  # 25 + 50


@pytest.mark.asyncio
async def test_t13_fractional_liters_precision(client: AsyncClient, superadmin_auth: dict):
    f = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Дробовий'})).json()['id']

    rec = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={
            'facility_id': f,
            'fuel_type': 'А-95',
            'liters': 33.333,
            'cost_total': 1933.31,
            'driver_name': 'Водій',
            'receipt_number': 'ДРІБ-01'
        }
    )
    assert rec.status_code == 201
    assert rec.json()['liters'] == 33.333

    stocks = (await client.get(f'/api/v1/fuel/stocks?facility_id={f}', headers=superadmin_auth)).json()
    assert stocks[0]['current_balance_l'] == 33.333


@pytest.mark.asyncio
async def test_t14_financial_decimal_arithmetic(client: AsyncClient, superadmin_auth: dict):
    f = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт Фінанси'})).json()['id']

    rec = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={
            'facility_id': f,
            'fuel_type': 'А-95',
            'liters': 17.5,
            'price_per_liter': 58.55,
            'driver_name': 'Водій',
            'receipt_number': 'ЧЕК-ФІН'
        }
    )
    assert rec.status_code == 201
    rec_data = rec.json()
    # 17.5 * 58.55 = 1024.625 -> 1024.63 rounded HALF_UP
    assert rec_data['cost_total'] == 1024.63
    assert rec_data['price_per_liter'] == 58.55


@pytest.mark.asyncio
async def test_t15_generator_fueling_facility_invariant(client: AsyncClient, superadmin_auth: dict):
    f1 = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт F1'})).json()['id']
    f2 = (await client.post('/api/v1/facilities', headers=superadmin_auth, json={'name': 'Об\'єкт F2'})).json()['id']

    # Stock on F1 (100L)
    rec = await client.post(
        '/api/v1/fuel/receipt',
        headers=superadmin_auth,
        json={'facility_id': f1, 'fuel_type': 'А-95', 'liters': 100.0, 'cost_total': 5800.0, 'driver_name': 'Водій', 'receipt_number': 'R-F1'}
    )
    assert rec.status_code == 201
    st1_id = rec.json()['stock_id']

    # Generator on F2
    gen2 = await client.post(
        '/api/v1/generator',
        headers=superadmin_auth,
        json={
            'name': 'Ген F2',
            'model': 'M',
            'manufacturer': 'Brand',
            'serial_number': 'SN-F2',
            'rated_power_kw': 5.0,
            'tank_capacity_l': 50.0,
            'fuel_type': 'А-95',
            'nominal_consumption_l_per_h': 2.2,
            'facility_id': f2
        }
    )
    assert gen2.status_code == 201
    gen2_id = gen2.json()['id']

    # Attempt cross-facility transfer from F1 stock into F2 generator -> 400 Bad Request
    res = await client.post(
        '/api/v1/fuel/transfer',
        headers=superadmin_auth,
        json={
            'facility_id': f1,
            'stock_id': st1_id,
            'generator_id': gen2_id,
            'liters': 20.0
        }
    )
    assert res.status_code == 400
    assert 'належать до різних об\'єктів' in res.json()['detail']
