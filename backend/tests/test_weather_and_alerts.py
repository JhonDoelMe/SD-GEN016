# -*- coding: utf-8 -*-
import pytest
from httpx import AsyncClient

from backend.app.services.weather_service import (
    extract_city_from_facility,
    get_generator_weather_tip,
    map_icon_to_emoji,
    get_facility_weather,
)
from backend.app.services.alert_service import (
    get_threat_display_info,
    get_operator_safety_advice,
    set_demo_alert,
    get_facility_alert,
    AlertLevel,
    AlertThreatType,
)
from backend.app.models.facility import Facility


def test_weather_helpers():
    # 1. City extraction
    f1 = Facility(name="Епіцентр Самар", address="вул. Гетьманська, 31", city="Самар")
    assert extract_city_from_facility(f1) == "Самар"

    f2 = Facility(name="Київський термінал", address="м. Київ, вул. Кільцева, 4")
    assert extract_city_from_facility(f2) == "Київ"

    f3 = Facility(name="Склад Захід", address="м. Львів, вул. Городоцька 15")
    assert extract_city_from_facility(f3) == "Львів"

    # 2. Generator tips
    tip_frost = get_generator_weather_tip(-12.0, 80, False)
    assert "Сильний мороз" in tip_frost

    tip_mild = get_generator_weather_tip(15.0, 60, False)
    assert "Оптимальні погодні умови" in tip_mild

    tip_heat = get_generator_weather_tip(33.0, 40, False)
    assert "Спека" in tip_heat

    # 3. Icon emoji mapping
    assert map_icon_to_emoji("01d") == "☀️"
    assert map_icon_to_emoji("02d") == "⛅"
    assert map_icon_to_emoji("10d") == "🌧️"
    assert map_icon_to_emoji("13d") == "❄️"


def test_alert_helpers():
    # 1. Display info
    title_b, icon_b = get_threat_display_info("ballistic", "red")
    assert "Балістична небезпека" in title_b
    assert icon_b == "🚀"

    title_d, icon_d = get_threat_display_info("drones", "yellow")
    assert "БПЛА" in title_d
    assert icon_d == "🛸"

    title_g, icon_g = get_threat_display_info("none", "green")
    assert "Відбій" in title_g
    assert icon_g == "🟢"

    # 2. Safety advice
    adv_red = get_operator_safety_advice("red", "ballistic")
    assert "КРИТИЧНА НЕБЕЗПЕКА" in adv_red
    assert "укриття" in adv_red

    adv_yellow = get_operator_safety_advice("yellow", "drones")
    assert "ПІДВИЩЕНА ЗАГРОЗА" in adv_yellow

    adv_green = get_operator_safety_advice("green", "none")
    assert "Тривоги немає" in adv_green


@pytest.mark.asyncio
async def test_facility_weather_and_alerts_endpoints(client: AsyncClient, superadmin_auth: dict, db_session):
    # 1. Create a test facility with city="Самар"
    fac_res = await client.post(
        "/api/v1/facilities",
        headers=superadmin_auth,
        json={
            "name": "Тестовий об'єкт Самар",
            "address": "вул. Гетьманська, 31",
            "city": "Самар",
            "timezone": "Europe/Kyiv"
        }
    )
    assert fac_res.status_code == 201
    fac = fac_res.json()
    fac_id = fac["id"]
    assert fac.get("city") == "Самар"

    # 2. Test Weather Endpoint
    weather_res = await client.get(f"/api/v1/facilities/{fac_id}/weather", headers=superadmin_auth)
    assert weather_res.status_code == 200
    w_data = weather_res.json()
    assert w_data["city"] == "Самар"
    assert "temp_c" in w_data
    assert "description" in w_data
    assert "generator_tip" in w_data

    # 3. Test Alerts Endpoint (default clean state)
    set_demo_alert("green", "none")
    alert_res = await client.get(f"/api/v1/facilities/{fac_id}/alert", headers=superadmin_auth)
    assert alert_res.status_code == 200
    a_data = alert_res.json()
    assert a_data["level"] == "green"
    assert a_data["is_active"] is False
    assert "Дніпропетровська область" in a_data["region_name"]

    # 4. Trigger Demo Yellow Alert (Drones / UAV)
    demo_yellow = await client.post(
        "/api/v1/facilities/demo-alert",
        headers=superadmin_auth,
        json={"level": "yellow", "threat_type": "drones"}
    )
    assert demo_yellow.status_code == 200

    alert_res_yellow = await client.get(f"/api/v1/facilities/{fac_id}/alert", headers=superadmin_auth)
    assert alert_res_yellow.status_code == 200
    ay_data = alert_res_yellow.json()
    assert ay_data["level"] == "yellow"
    assert ay_data["is_active"] is True
    assert ay_data["threat_type"] == "drones"
    assert ay_data["threat_icon"] == "🛸"

    # 5. Trigger Demo Red Alert (Ballistic)
    demo_red = await client.post(
        "/api/v1/facilities/demo-alert",
        headers=superadmin_auth,
        json={"level": "red", "threat_type": "ballistic"}
    )
    assert demo_red.status_code == 200

    # 6. Test Combined Status Indicators Endpoint
    indicators_res = await client.get(f"/api/v1/facilities/{fac_id}/status-indicators", headers=superadmin_auth)
    assert indicators_res.status_code == 200
    ind_data = indicators_res.json()
    assert "weather" in ind_data
    assert "alert" in ind_data
    assert ind_data["weather"]["city"] == "Самар"
    assert ind_data["alert"]["level"] == "red"
    assert ind_data["alert"]["threat_icon"] == "🚀"
    assert "КРИТИЧНА НЕБЕЗПЕКА" in ind_data["alert"]["operator_advice"]

    # 7. Reset demo alert back to green
    set_demo_alert("green", "none")
    alert_reset = await client.get(f"/api/v1/facilities/{fac_id}/alert", headers=superadmin_auth)
    assert alert_reset.json()["level"] == "green"
