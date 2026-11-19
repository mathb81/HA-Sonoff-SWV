"""A plan loaded from the valve could not be saved again.

In capacity mode the valve reports the unused durations as 0
(irrigation_duration, interval_duration). Loading such a plan into the form
copied those zeros, and saving it sent them back: Zigbee2MQTT refuses the
whole plan ("irrigation_plan_settings invalid irrigation_duration, expected
integer in range [1, 60]"), captured on a real SWV-ZFE on 2026-11-19 (plan 1
of "Arrosage Jasmin Terrasse", loaded from its July report). The two form
fields also accept 1 to 60 only, so the user could not even correct them.
"""

from __future__ import annotations

import json

from custom_components.sonoff_swv.button import BUTTONS, SonoffSWVButton

SAVE_PLAN = next(d for d in BUTTONS if d.key == "irrigation_plan_settings")

JULY_REPORT = {
    "plan_index": 1,
    "enable_state": False,
    "loop_type_mode": "weekdays",
    "loop_type_interval_days": 0,
    "loop_type_week_days": {
        day: True
        for day in (
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        )
    },
    "enable_date": "2026-07-11",
    "start_time": "19:00",
    "irrigation_mode": "capacity",
    "irrigation_amount": 75,
    "irrigation_amount_unit": "liter",
    "irrigation_duration": 0,
    "irrigation_total_duration": 0,
    "interval_duration": 0,
    "fail_safe": 90,
    "create_datetime": "2026-07-11T23:57:00+02:00",
}


def published_plan(hass) -> dict:
    for _topic, payload in reversed(hass.mqtt_published):
        data = json.loads(payload) if isinstance(payload, str) else payload
        if "irrigation_plan_settings" in data:
            return data["irrigation_plan_settings"]
    raise AssertionError("no plan was published")


async def test_plan_loaded_from_a_report_can_be_saved(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    coordinator.update_from_device({"irrigation_plan_report": JULY_REPORT})
    await coordinator.async_load_plan_into_form(1)

    device = coordinator.device
    assert device.irrigation_plan_duration >= 1, "the form shows a value it refuses"
    assert device.irrigation_plan_interval_duration >= 1

    await SonoffSWVButton(coordinator, SAVE_PLAN).async_press()

    plan = published_plan(hass)
    assert 1 <= plan["irrigation_duration"] <= 60, (
        "Zigbee2MQTT refuses the whole plan with this duration"
    )
    assert 1 <= plan["interval_duration"] <= 60
    assert plan["irrigation_amount"] == 75
