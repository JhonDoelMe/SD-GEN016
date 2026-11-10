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

    # 2. Generator tips & 5-day forecast parsing
    tip_frost = get_generator_weather_tip(-12.0, 80, False)
    assert "Сильний мороз" in tip_frost

    tip_mild = get_generator_weather_tip(15.0, 60, False)
    assert "Оптимальні погодні умови" in tip_mild

    tip_heat = get_generator_weather_tip(33.0, 40, False)
    assert "Спека" in tip_heat

    from backend.app.services.weather_service import parse_5day_forecast
    mock_forecast_payload = {
        "list": [
            {
                "dt_txt": "2026-11-11 12:00:00",
                "main": {"temp": 6.5, "temp_min": 2.1, "temp_max": 7.4},
                "weather": [{"icon": "10d", "description": "помірний дощ"}],
                "pop": 0.85
            },
            {
                "dt_txt": "2026-11-12 12:00:00",
                "main": {"temp": -2.0, "temp_min": -3.4, "temp_max": 1.2},
                "weather": [{"icon": "13n", "description": "невеликий сніг"}],
                "pop": 0.6
            }
        ]
    }
    parsed_days = parse_5day_forecast(mock_forecast_payload)
    assert len(parsed_days) == 2
    assert parsed_days[0]["date"] == "2026-11-11"
    assert parsed_days[0]["temp_max_formatted"] == "+7°"
    assert parsed_days[0]["temp_min_formatted"] == "+2°"
    assert parsed_days[0]["pop_percent"] == 85
    assert parsed_days[1]["icon_code"] == "13d"
    assert parsed_days[1]["icon_emoji"] == "❄️"

    # Proactive frost warning when current temp is mild (+5°C) but forecast has frost (-3.4°C)
    tip_upcoming_frost = get_generator_weather_tip(5.0, 65, False, forecast_days=parsed_days)
    assert "заморозки" in tip_upcoming_frost

    # 3. Icon emoji mapping
    assert map_icon_to_emoji("01d") == "☀️"
    assert map_icon_to_emoji("02d") == "⛅"
    assert map_icon_to_emoji("10d") == "🌧️"
    assert map_icon_to_emoji("13d") == "❄️"

    # 4. Anti-duplication test when city contains oblast
    from backend.app.services.weather_service import clean_city_and_region
    c_samar, r_samar = clean_city_and_region("Самар, Дніпропетровська область.")
    assert c_samar == "Самар"
    assert r_samar == "Дніпропетровська область"

    f4 = Facility(name="Самар-Центр", address="м. Самар", city="Самар, Дніпропетровська область.")
    assert extract_city_from_facility(f4) == "Самар"

    c_kyiv, r_kyiv = clean_city_and_region("м. Київ")
    assert c_kyiv == "Київ"
    assert r_kyiv == "м. Київ"

    c_dnipro, r_dnipro = clean_city_and_region("Дніпро, Дніпропетровська обл.")
    assert c_dnipro == "Дніпро"
    assert r_dnipro == "Дніпропетровська область"


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

    adv_art = get_operator_safety_advice("red", "artillery")
    assert "АРТОБСТРІЛ" in adv_art

    # 3. Hierarchical alert matching & parsing
    from backend.app.services.alert_service import match_target_alert, parse_alert_payload
    mock_active_alerts = [
        {
            "id": 1,
            "location_title": "Самарівський район",
            "location_type": "raion",
            "alert_type": "air_raid",
            "location_oblast": "Дніпропетровська область",
            "alert_level": "red",
            "threats": [{"threat_type": "unspecified_missiles", "level": "red", "started_at": "2026-11-05T19:14:21.000Z"}]
        },
        {
            "id": 2,
            "location_title": "м. Київ",
            "location_type": "oblast",
            "alert_type": "air_raid",
            "location_oblast": "м. Київ",
            "alert_level": "yellow",
            "threats": None
        },
        {
            "id": 3,
            "location_title": "Нікопольська міська територіальна громада",
            "location_type": "hromada",
            "location_raion": "Нікопольський район",
            "alert_type": "artillery_shelling",
            "location_oblast": "Дніпропетровська область",
            "alert_level": "red",
            "threats": None
        }
    ]

    # Samar facility matches Samarivskyi raion red alert
    al_samar = match_target_alert(mock_active_alerts, "Дніпропетровська область", "Самар")
    assert al_samar is not None
    p_samar = parse_alert_payload(al_samar)
    assert p_samar["is_active"] is True
    assert p_samar["level"] == "red"
    assert p_samar["threat_type"] == "cruise"

    # Kyiv facility matches Kyiv yellow alert
    al_kyiv = match_target_alert(mock_active_alerts, "м. Київ", "Київ")
    assert al_kyiv is not None
    p_kyiv = parse_alert_payload(al_kyiv)
    assert p_kyiv["is_active"] is True
    assert p_kyiv["level"] == "yellow"
    assert p_kyiv["threat_type"] == "drones"

    # Nikopol facility matches artillery shelling
    al_nikopol = match_target_alert(mock_active_alerts, "Дніпропетровська область", "Нікополь")
    assert al_nikopol is not None
    p_nikopol = parse_alert_payload(al_nikopol)
    assert p_nikopol["is_active"] is True
    assert p_nikopol["level"] == "red"
    assert p_nikopol["threat_type"] == "artillery"

    # Lviv facility has no active alerts
    al_lviv = match_target_alert(mock_active_alerts, "Львівська область", "Львів")
    assert al_lviv is None
    p_lviv = parse_alert_payload(al_lviv)
    assert p_lviv["is_active"] is False
    assert p_lviv["level"] == "green"

    # 4. UkraineAlarm v3 schema matching & parsing
    from backend.app.services.alert_service import (
        match_ukraine_alarm_regions,
        parse_ukraine_alarm_payload,
        fuse_provider_results,
    )
    mock_ua_alarm_v3 = [
        {
            "regionId": "43",
            "regionType": "District",
            "regionName": "Самарівський район",
            "regionEngName": "Samarivskyi district",
            "lastUpdate": "2026-11-10T18:02:50Z",
            "activeAlerts": [
                {
                    "regionId": "43",
                    "regionType": "District",
                    "type": "AIR",
                    "lastUpdate": "2026-11-10T18:02:50Z",
                    "activeAlertLevels": [
                        {
                            "alertLevel": "Red",
                            "reason": "",
                            "createdAt": "2026-11-10T18:02:51Z"
                        }
                    ]
                }
            ]
        },
        {
            "regionId": "335",
            "regionType": "Community",
            "regionName": "м. Нікополь та Нікопольська територіальна громада",
            "lastUpdate": "2026-11-10T18:05:00Z",
            "activeAlerts": [
                {
                    "regionId": "335",
                    "regionType": "Community",
                    "type": "ARTILLERY",
                    "lastUpdate": "2026-11-10T18:05:00Z",
                    "activeAlertLevels": [
                        {
                            "alertLevel": "Red",
                            "reason": "",
                            "createdAt": "2026-11-10T18:05:01Z"
                        }
                    ]
                }
            ]
        },
        {
            "regionId": "31",
            "regionType": "State",
            "regionName": "м. Київ",
            "lastUpdate": "2026-11-10T18:10:00Z",
            "activeAlerts": [
                {
                    "regionId": "31",
                    "regionType": "State",
                    "type": "AIR",
                    "lastUpdate": "2026-11-10T18:10:00Z",
                    "activeAlertLevels": [
                        {
                            "alertLevel": "Yellow",
                            "reason": "UAV threat",
                            "createdAt": "2026-11-10T18:10:01Z"
                        }
                    ]
                }
            ]
        }
    ]

    ua_samar = match_ukraine_alarm_regions(mock_ua_alarm_v3, "Дніпропетровська область", "Самар")
    assert len(ua_samar) == 1
    p_ua_samar = parse_ukraine_alarm_payload(ua_samar)
    assert p_ua_samar["is_active"] is True
    assert p_ua_samar["level"] == "red"
    assert p_ua_samar["started_at"] == "2026-11-10T18:02:51Z"

    ua_nikopol = match_ukraine_alarm_regions(mock_ua_alarm_v3, "Дніпропетровська область", "Нікополь")
    p_ua_nikopol = parse_ukraine_alarm_payload(ua_nikopol)
    assert p_ua_nikopol["is_active"] is True
    assert p_ua_nikopol["level"] == "red"
    assert p_ua_nikopol["threat_type"] == "artillery"

    ua_kyiv = match_ukraine_alarm_regions(mock_ua_alarm_v3, "м. Київ", "Київ")
    p_ua_kyiv = parse_ukraine_alarm_payload(ua_kyiv)
    assert p_ua_kyiv["is_active"] is True
    assert p_ua_kyiv["level"] == "yellow"
    assert p_ua_kyiv["threat_type"] == "drones"

    ua_lviv = match_ukraine_alarm_regions(mock_ua_alarm_v3, "Львівська область", "Львів")
    p_ua_lviv = parse_ukraine_alarm_payload(ua_lviv)
    assert p_ua_lviv["is_active"] is False
    assert p_ua_lviv["level"] == "green"

    # 5. Dual-Provider Fusion & Insurance Rule (Страхування від передчасного відбою)
    # Case A: Both agree on Green
    fused_green = fuse_provider_results(p_lviv, p_ua_lviv)
    assert fused_green["is_active"] is False
    assert fused_green["level"] == "green"
    assert fused_green["verification_status"] == "verified"

    # Case B: Both agree on Red, alerts.in.ua enriches specific threat_type ("cruise")
    fused_red = fuse_provider_results(p_samar, p_ua_samar)
    assert fused_red["is_active"] is True
    assert fused_red["level"] == "red"
    assert fused_red["threat_type"] == "cruise"
    assert fused_red["verification_status"] == "verified"
    assert fused_red["provider"] == "Alerts.in.ua + UkraineAlarm"
    assert fused_red["verification_note"] == "Тривогу підтверджено обома джерелами (Alerts.in.ua + UkraineAlarm)"

    # Case C: Premature all-clear on one provider -> holds worst-case active alert!
    fused_insurance_1 = fuse_provider_results(p_lviv, p_ua_samar)
    assert fused_insurance_1["is_active"] is True
    assert fused_insurance_1["level"] == "red"
    assert fused_insurance_1["verification_status"] == "insurance_hold"
    assert "Страхування" in fused_insurance_1["verification_note"]

    # Case D: Reverse discrepancy (alerts.in.ua still Yellow, UkraineAlarm already Green)
    fused_insurance_2 = fuse_provider_results(p_kyiv, p_ua_lviv)
    assert fused_insurance_2["is_active"] is True
    assert fused_insurance_2["level"] == "yellow"
    assert fused_insurance_2["threat_type"] == "drones"
    assert fused_insurance_2["verification_status"] == "insurance_hold"

    # Case E: Level discrepancy (alerts.in.ua Yellow vs UkraineAlarm Red) -> picks Red
    fused_insurance_3 = fuse_provider_results(p_kyiv, p_ua_samar)
    assert fused_insurance_3["is_active"] is True
    assert fused_insurance_3["level"] == "red"
    assert fused_insurance_3["verification_status"] == "insurance_hold"


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
