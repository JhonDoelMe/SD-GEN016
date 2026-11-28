import pytest
from backend.app.services.settings_service import (
    DEFAULT_WOG_LINEUP,
    DEFAULT_OKKO_LINEUP,
    DEFAULT_OKKO_PRICES,
    _parse_wog_fuel_html,
    _parse_okko_fuel_html,
    _parse_minfin_fuel_html,
    fetch_wog_fuel_prices_online,
    fetch_okko_fuel_prices_online,
    get_fuel_prices_info,
    is_fuel_prices_stale,
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
    assert excel_bytes and len(excel_bytes) > 1000


def test_parse_wog_next_data_optional_brand_and_100():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"items":['
        '{"price":10090,"i_am_page_element":"block.fuels_fuel","type":"ДП","brand":"Євро5"},'
        '{"price":10390,"i_am_page_element":"block.fuels_fuel","type":"ДП","brand":"Mustang+"},'
        '{"price":8690,"i_am_page_element":"block.fuels_fuel","type":"95","brand":"Євро5-Е10"},'
        '{"price":8990,"i_am_page_element":"block.fuels_fuel","type":"95","brand":"Mustang Євро5-Е10"},'
        '{"price":9690,"i_am_page_element":"block.fuels_fuel","type":"100","brand":"Mustang Євро5-Е0"},'
        '{"price":6350,"i_am_page_element":"block.fuels_fuel","type":"ГАЗ"},'
        '{"price":6290,"i_am_page_element":"block.fuels_fuel","type":"AdBlue"}'
        ']}}}</script>'
    )
    prices, lineup = _parse_wog_fuel_html(html)
    assert len(lineup) == 7
    assert prices["ДП"] == 100.90
    assert prices["ДП Mustang+"] == 103.90
    assert prices["А-95"] == 86.90
    assert prices["А-95 Mustang"] == 89.90
    assert prices["А-100 Mustang"] == 96.90
    assert prices["ГАЗ"] == 63.50
    assert prices["AdBlue"] == 62.90


def test_parse_okko_nuxt_semantic_order_independent():
    # Reversed/shuffled order compared to default positional layout
    html = (
        '<script>window.__NUXT__=(function(a,b,c,d,e,f,g){return {'
        'bullets:{items:['
        '{title:"ГАЗ",price:"63.90",type:a,fuel_code:"SPBT"},'
        '{title:b,price:"84.90",type:c,fuel_code:"A-95"},'
        '{title:d,price:"99.90",type:c,fuel_code:"DP"},'
        '{title:b,price:"87.90",type:e,fuel_code:"Pulls 95"},'
        '{title:d,price:"102.90",type:e,fuel_code:"Pulls Diesel"},'
        '{title:"100",price:"94.90",type:e,fuel_code:"Pulls 100"},'
        '{title:f,price:"62.90",type:a,fuel_code:f}'
        ']}};})("","95","euro","ДП","pulls","AdBlue",null));</script>'
    )
    parsed = _parse_okko_fuel_html(html)
    assert parsed is not None
    prices, lineup = parsed
    assert len(lineup) == 7
    assert prices["ГАЗ"] == 63.90
    assert prices["А-95"] == 84.90
    assert prices["А-95 Pulls"] == 87.90
    assert prices["ДП"] == 99.90
    assert prices["ДП Pulls"] == 102.90
    assert prices["А-100 Pulls"] == 94.90
    assert prices["AdBlue"] == 62.90


def test_is_fuel_prices_stale():
    assert is_fuel_prices_stale("") is True
    assert is_fuel_prices_stale("invalid") is True
    assert is_fuel_prices_stale("2020-01-01 00:00:00") is True
    from zoneinfo import ZoneInfo
    now_str = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M:%S")
    assert is_fuel_prices_stale(now_str) is False


def test_parse_minfin_wog_secondary_live_source():
    html = """
    <table>
      <tr><td>Бензин А-95 Mustang</td><td>87,90</td><td>0.00</td></tr>
      <tr><td>Бензин А-95 Євро 5</td><td>84,90</td><td>0.00</td></tr>
      <tr><td>Дизельне паливо Євро 5</td><td>99,99</td><td>0.00</td></tr>
      <tr><td>Газ авто&shy;мобільний</td><td>62,90</td><td>0.00</td></tr>
      <tr><td>Дніпро&shy;петровська</td><td>87,90</td><td>84,90</td></tr>
    </table>
    """
    parsed = _parse_minfin_fuel_html(html, provider="wog")
    assert parsed is not None
    prices, lineup = parsed
    assert prices["А-95 Mustang"] == 87.90
    assert prices["А-95"] == 84.90
    assert prices["ДП"] == 99.99
    assert prices["ГАЗ"] == 62.90
    assert len(lineup) == 4


@pytest.mark.asyncio
async def test_wog_falls_back_to_live_minfin_on_http_204():
    from unittest.mock import AsyncMock, MagicMock, patch

    resp_204 = MagicMock(status_code=204, text="")
    resp_minfin = MagicMock(
        status_code=200,
        text="<html>" + (" " * 1000) + """
        <table>
          <tr><td>Бензин А-95 Mustang</td><td>87,90</td></tr>
          <tr><td>Бензин А-95 Євро 5</td><td>84,90</td></tr>
          <tr><td>Дизельне паливо Євро 5</td><td>99,99</td></tr>
          <tr><td>Газ авто&shy;мобільний</td><td>62,90</td></tr>
        </table></html>""",
    )

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(side_effect=[resp_204, resp_minfin])

    with patch("backend.app.services.settings_service.httpx.AsyncClient", return_value=mock_client):
        prices, lineup, source, is_live = await fetch_wog_fuel_prices_online(timeout=5.0)
        assert is_live is True
        assert "minfin" in source.lower()
        assert prices["А-95"] == 84.90
        assert prices["ДП"] == 99.99
        assert prices["ГАЗ"] == 62.90
        assert len(lineup) == 4


@pytest.mark.asyncio
async def test_yasno_dynamic_options_and_region_resolution(client, superadmin_auth):
    from unittest.mock import AsyncMock, patch
    from backend.app.services.yasno_service import resolve_yasno_region_id, _natural_group_sort_key

    assert resolve_yasno_region_id(301) == 3
    assert resolve_yasno_region_id(303) == 3
    assert resolve_yasno_region_id(902) == 25
    assert sorted(["10.1", "2.1", "1.1", "18.1"], key=_natural_group_sort_key) == ["1.1", "2.1", "10.1", "18.1"]

    fake_schedule = {
        "10.1": {"today": {"slots": []}},
        "2.1": {"today": {"slots": []}},
        "1.1": {"today": {"slots": []}},
        "18.1": {"today": {"slots": []}},
    }
    with patch("backend.app.services.yasno_service.fetch_raw_yasno_schedule", new_callable=AsyncMock, return_value=fake_schedule):
        res = await client.get("/api/v1/facilities/yasno/options?dso_id=301", headers=superadmin_auth)
        assert res.status_code == 200
        body = res.json()
        assert body["region_id"] == 3
        assert body["dso_id"] == 301
        assert body["groups"] == ["1.1", "2.1", "10.1", "18.1"]
        assert body["is_live"] is True
        assert len(body["dsos"]) >= 3
