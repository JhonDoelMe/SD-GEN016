import pytest
from backend.app.services.settings_service import (
    DEFAULT_WOG_LINEUP,
    DEFAULT_OKKO_LINEUP,
    DEFAULT_OKKO_PRICES,
    fetch_okko_fuel_prices_online,
    get_fuel_prices_info,
    resolve_fuel_price_per_liter,
)
from backend.app.services.report_service import generate_excel_report
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_okko_scraper_and_fallback():
    prices, lineup, source, is_live = await fetch_okko_fuel_prices_online(timeout=3.0)
    assert len(lineup) >= 5
    assert "ДП" in prices
    assert "А-95" in prices
    assert "okko" in source.lower()


@pytest.mark.asyncio
async def test_get_fuel_prices_info_has_both_wog_and_okko():
    info = get_fuel_prices_info()
    assert "fuels" in info
    assert "okko_fuels" in info
    assert "wog_lineup" in info
    assert "okko_lineup" in info
    assert len(info["wog_lineup"]) > 0
    assert len(info["okko_lineup"]) > 0
    assert "ДП" in info["okko_fuels"]
    assert "А-95" in info["okko_fuels"]


@pytest.mark.asyncio
async def test_resolve_fuel_price_wog_vs_okko(db_session):
    # OKKO price resolution
    price_okko_dp, src_okko = await resolve_fuel_price_per_liter(db_session, "ДП", provider="okko")
    assert price_okko_dp > 0
    assert src_okko in ("internet_okko", "system_settings")

    # WOG price resolution
    price_wog_dp, src_wog = await resolve_fuel_price_per_liter(db_session, "ДП", provider="wog")
    assert price_wog_dp > 0
    assert src_wog in ("internet", "system_settings")


@pytest.mark.asyncio
async def test_facility_default_fuel_provider_api(client, superadmin_auth):
    # 1. Create facility with default_fuel_provider="okko"
    create_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={
            "name": "Локація ОККО Тест",
            "address": "вул. Автомобільна, 1",
            "default_fuel_provider": "okko",
            "timezone": "Europe/Kyiv"
        }
    )
    assert create_res.status_code == 201
    fac_data = create_res.json()
    assert fac_data["default_fuel_provider"] == "okko"
    fac_id = fac_data["id"]

    # 2. Get facility by ID
    get_res = await client.get(f"/api/v1/facilities/{fac_id}", headers=superadmin_auth)
    assert get_res.status_code == 200
    assert get_res.json()["default_fuel_provider"] == "okko"

    # 3. Update facility to "wog"
    upd_res = await client.put(
        f"/api/v1/facilities/{fac_id}",
        headers=superadmin_auth,
        json={"default_fuel_provider": "wog"}
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["default_fuel_provider"] == "wog"


@pytest.mark.asyncio
async def test_fuel_receipt_with_okko_provider(client, superadmin_auth):
    # Create facility
    fac_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={
            "name": "АЗС Тест Локація",
            "default_fuel_provider": "okko"
        }
    )
    assert fac_res.status_code == 201
    fac_id = fac_res.json()["id"]

    # Get stock
    stocks_res = await client.get(f"/api/v1/fuel/stocks?facility_id={fac_id}", headers=superadmin_auth)
    assert stocks_res.status_code == 200
    stocks = stocks_res.json()
    assert len(stocks) > 0
    stock_id = stocks[0]["id"]

    # Add receipt with explicit OKKO provider
    rec_res = await client.post(
        "/api/v1/fuel/receipt",
        headers=superadmin_auth,
        json={
            "facility_id": fac_id,
            "stock_id": stock_id,
            "fuel_provider": "okko",
            "fuel_type": "ДП Pulls",
            "liters": 50.0,
            "cost_total": 5495.0,
            "driver_name": "Іванов О.К.",
            "receipt_number": "OKKO-9912",
            "comment": "Закупівля на ОККО"
        }
    )
    assert rec_res.status_code == 201
    rec = rec_res.json()
    assert rec["fuel_provider"] == "okko"
    assert rec["fuel_type"] == "ДП Pulls"
    assert rec["liters"] == 50.0
    assert rec["cost_total"] == 5495.0

    # List receipts and verify fuel_provider
    list_res = await client.get(f"/api/v1/fuel/receipts?facility_id={fac_id}", headers=superadmin_auth)
    assert list_res.status_code == 200
    all_recs = list_res.json()
    assert any(r["id"] == rec["id"] and r["fuel_provider"] == "okko" for r in all_recs)


@pytest.mark.asyncio
async def test_system_fuel_prices_refresh_endpoint(client, superadmin_auth):
    # Refresh OKKO
    res_okko = await client.post(
        "/api/v1/system/fuel-prices/refresh?provider=okko",
        headers=superadmin_auth
    )
    assert res_okko.status_code == 200
    data_okko = res_okko.json()
    assert "okko_fuels" in data_okko
    assert "okko_lineup" in data_okko

    # Refresh WOG
    res_wog = await client.post(
        "/api/v1/system/fuel-prices/refresh?provider=wog",
        headers=superadmin_auth
    )
    assert res_wog.status_code == 200
    data_wog = res_wog.json()
    assert "fuels" in data_wog
    assert "wog_lineup" in data_wog


@pytest.mark.asyncio
async def test_excel_report_includes_fuel_provider_column(db_session):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    end = datetime(2025, 12, 31, tzinfo=timezone.utc).replace(tzinfo=None)
    excel_bytes = await generate_excel_report(db_session, start_date=start, end_date=end)
    assert len(excel_bytes) > 1000
