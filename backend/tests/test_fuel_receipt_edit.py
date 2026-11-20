"""Tests for editing fuel receipts (Admin / SuperAdmin, <= 72h window, stock & canister auto-sync)."""

import datetime
import json
import pytest
from sqlalchemy import select

from backend.app.models.audit import AuditLog
from backend.app.models.canister import CanisterPool, CanisterTransaction
from backend.app.models.fuel import FuelReceipt, FuelStock


@pytest.mark.asyncio
async def test_edit_receipt_rbac_and_basic_fields(client, operator_auth, viewer_auth, admin_auth, superadmin_auth, db_session):
    # Create a fuel receipt
    r_create = await client.post(
        "/api/v1/fuel/receipt",
        headers=superadmin_auth,
        json={
            "fuel_provider": "wog",
            "fuel_type": "А-95",
            "liters": 40.0,
            "cost_total": 2400.0,
            "driver_name": "Іваненко І.І.",
            "receipt_number": "REC-100",
        },
    )
    assert r_create.status_code == 201
    rec_id = r_create.json()["id"]

    # Operator and Viewer must be forbidden (403)
    for headers in (operator_auth, viewer_auth):
        r_forbid = await client.put(
            f"/api/v1/fuel/receipt/{rec_id}",
            headers=headers,
            json={"fuel_provider": "okko", "edit_reason": "Спроба оператора"},
        )
        assert r_forbid.status_code == 403

    # Admin can edit provider, price, liters, receipt number
    r_edit = await client.put(
        f"/api/v1/fuel/receipt/{rec_id}",
        headers=admin_auth,
        json={
            "fuel_provider": "okko",
            "liters": 50.0,
            "cost_total": 3100.0,
            "driver_name": "Петренко П.П.",
            "receipt_number": "REC-100-FIX",
            "comment": "Виправлено мережу та об'єм",
            "edit_reason": "Помилка при внесенні чека АЗС",
        },
    )
    assert r_edit.status_code == 200
    body = r_edit.json()
    assert body["fuel_provider"] == "okko"
    assert body["liters"] == pytest.approx(50.0)
    assert body["cost_total"] == pytest.approx(3100.0)
    assert body["price_per_liter"] == pytest.approx(62.0)
    assert body["driver_name"] == "Петренко П.П."
    assert body["receipt_number"] == "REC-100-FIX"

    # Stock balance increased by +10.0 L (40 -> 50)
    stock = await db_session.get(FuelStock, body["stock_id"])
    await db_session.refresh(stock)
    assert float(stock.current_balance_l) == pytest.approx(50.0)

    # Audit log recorded FUEL_RECEIPT_UPDATED with before/after diff
    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "FUEL_RECEIPT_UPDATED").order_by(AuditLog.id.desc())
        )
    ).scalars().first()
    assert audit is not None
    details = json.loads(audit.details_json)
    assert details["before"]["fuel_provider"] == "wog"
    assert details["after"]["fuel_provider"] == "okko"
    assert details["delta_liters"] == pytest.approx(10.0)
    assert details["reason"] == "Помилка при внесенні чека АЗС"


@pytest.mark.asyncio
async def test_edit_receipt_72h_window_and_negative_stock_protection(client, superadmin_auth, db_session):
    r_create = await client.post(
        "/api/v1/fuel/receipt",
        headers=superadmin_auth,
        json={
            "fuel_provider": "wog",
            "fuel_type": "А-95",
            "liters": 30.0,
            "cost_total": 1800.0,
            "driver_name": "Водій 1",
            "receipt_number": "REC-NEG-1",
        },
    )
    assert r_create.status_code == 201
    rec_id = r_create.json()["id"]
    stock_id = r_create.json()["stock_id"]

    # Transfer 20 L to tank so only 10 L remains on stock
    r_tr = await client.post(
        "/api/v1/fuel/transfer",
        headers=superadmin_auth,
        json={"stock_id": stock_id, "liters": 20.0},
    )
    assert r_tr.status_code == 201

    # Trying to reduce receipt from 30 L to 15 L (delta -15 L > 10 L remaining) -> 400
    r_neg = await client.put(
        f"/api/v1/fuel/receipt/{rec_id}",
        headers=superadmin_auth,
        json={"liters": 15.0, "cost_total": 900.0, "edit_reason": "Зменшення нижче витраченого"},
    )
    assert r_neg.status_code == 400
    assert "від'ємним" in r_neg.json()["detail"]

    # Price safeguard blocks anomalous price without force_confirm, passes with force_confirm
    r_price_block = await client.put(
        f"/api/v1/fuel/receipt/{rec_id}",
        headers=superadmin_auth,
        json={"liters": 30.0, "cost_total": 90.0, "edit_reason": "Тест запобіжника ціни"},
    )
    assert r_price_block.status_code == 400
    r_price_ok = await client.put(
        f"/api/v1/fuel/receipt/{rec_id}",
        headers=superadmin_auth,
        json={"liters": 30.0, "cost_total": 90.0, "edit_reason": "Тест override ціни", "force_confirm": True},
    )
    assert r_price_ok.status_code == 200

    # Backdate receipt created_at to 73 hours ago -> 403 Forbidden
    rec_row = await db_session.get(FuelReceipt, rec_id)
    rec_row.created_at = rec_row.created_at - datetime.timedelta(hours=73)
    await db_session.commit()

    r_expired = await client.put(
        f"/api/v1/fuel/receipt/{rec_id}",
        headers=superadmin_auth,
        json={"fuel_provider": "okko", "edit_reason": "Після 72 годин"},
    )
    assert r_expired.status_code == 403
    assert "72 годин" in r_expired.json()["detail"]


@pytest.mark.asyncio
async def test_edit_receipt_auto_syncs_canister_pool_variant_1(client, superadmin_auth, db_session):
    # Ensure default stock exists for facility 1
    r_stocks = await client.get("/api/v1/fuel/stocks?facility_id=1", headers=superadmin_auth)
    assert r_stocks.status_code == 200
    stock_id = r_stocks.json()[0]["id"]

    # Create canister pool (5 x 20 L = 100 L max capacity, initially empty)
    r_pool = await client.post(
        "/api/v1/fuel/canisters",
        headers=superadmin_auth,
        json={
            "facility_id": 1,
            "stock_id": stock_id,
            "name": "Каністри 20л",
            "canister_volume_l": 20.0,
            "full_count": 0,
            "empty_count": 5,
            "away_refill_count": 0,
            "reserve_liters": 0.0,
        },
    )
    assert r_pool.status_code == 201
    pool_data = r_pool.json()
    pool_id = pool_data["id"]

    # Receive 2 canisters (+40 L) with receipt
    r_recv = await client.post(
        f"/api/v1/fuel/canisters/{pool_id}/receive",
        headers=superadmin_auth,
        json={
            "count": 2,
            "source": "auto",
            "create_receipt": True,
            "fuel_provider": "wog",
            "cost_total": 2400.0,
            "driver_name": "Водій Каністр",
            "receipt_number": "CAN-REC-1",
        },
    )
    assert r_recv.status_code == 200

    rec_row = (
        await db_session.execute(select(FuelReceipt).where(FuelReceipt.receipt_number == "CAN-REC-1"))
    ).scalars().first()
    assert rec_row is not None

    # Increase receipt from 40 L to 65 L -> should sync pool to 3 full canisters + 5 L reserve
    r_edit_ok = await client.put(
        f"/api/v1/fuel/receipt/{rec_row.id}",
        headers=superadmin_auth,
        json={
            "fuel_provider": "other",
            "liters": 65.0,
            "cost_total": 3900.0,
            "edit_reason": "Уточнено об'єм за фактичним чеком",
        },
    )
    assert r_edit_ok.status_code == 200
    assert r_edit_ok.json()["fuel_provider"] == "other"

    pool_row = await db_session.get(CanisterPool, pool_id)
    await db_session.refresh(pool_row)
    assert pool_row.full_count == 3
    assert pool_row.empty_count == 2
    assert float(pool_row.reserve_liters) == pytest.approx(5.0)

    # CanisterTransaction with operation RECEIPT_EDIT recorded
    tx = (
        await db_session.execute(
            select(CanisterTransaction)
            .where(CanisterTransaction.pool_id == pool_id, CanisterTransaction.operation == "RECEIPT_EDIT")
        )
    ).scalars().first()
    assert tx is not None
    assert float(tx.liters_delta) == pytest.approx(25.0)

    # Increasing beyond pool max capacity (100 L) -> rejected with 400
    r_over = await client.put(
        f"/api/v1/fuel/receipt/{rec_row.id}",
        headers=superadmin_auth,
        json={
            "liters": 120.0,
            "cost_total": 7200.0,
            "edit_reason": "Перевищення місткості пулу",
        },
    )
    assert r_over.status_code == 400
    assert "місткість" in r_over.json()["detail"]
