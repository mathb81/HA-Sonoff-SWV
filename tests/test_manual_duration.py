"""Bug 2: the duration set for manual watering was not the one sent.

For manual watering Zigbee2MQTT only reads irrigation_mode,
irrigation_duration, irrigation_amount, irrigation_amount_unit and
fail_safe (manual_default_settings in zigbee-herdsman-converters); the
pause is fixed at 10 minutes. The integration also exposed "Manual
irrigation total duration" and "Manual interval duration" and published
them: changing them had no effect, and the example dashboard showed the
first one as the duration of manual watering.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import ha_stubs

from custom_components.sonoff_swv import coordinator as coordinator_module
from custom_components.sonoff_swv import number as number_platform
from custom_components.sonoff_swv.number import NUMBERS, SonoffSWVNumber

from conftest import IEEE

# Fields read by the manual_default_settings converter of Zigbee2MQTT.
READ_BY_ZIGBEE2MQTT = {
    "irrigation_mode",
    "irrigation_duration",
    "irrigation_amount",
    "irrigation_amount_unit",
    "fail_safe",
}

EXAMPLE_DASHBOARD = Path(__file__).parents[1] / "examples" / "dashboard.yaml"


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(coordinator_module.asyncio, "sleep", _sleep)


def manual_payloads(hass) -> list[dict]:
    payloads = [json.loads(payload) for _topic, payload in hass.mqtt_published]
    return [p["manual_default_settings"] for p in payloads if "manual_default_settings" in p]


async def test_manual_settings_sent_are_all_read_by_zigbee2mqtt(make_coordinator, hass):
    coordinator = await make_coordinator()

    await coordinator.async_start_manual_irrigation()

    sent = manual_payloads(hass)[-1]
    ignored = set(sent) - READ_BY_ZIGBEE2MQTT
    assert not ignored, f"published but ignored by Zigbee2MQTT: {sorted(ignored)}"


def read_fields(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k in READ_BY_ZIGBEE2MQTT}


@pytest.mark.parametrize(
    "description",
    [d for d in NUMBERS if d.key.startswith("manual_")],
    ids=lambda d: d.key,
)
async def test_every_manual_setting_changes_what_the_valve_gets(
    make_coordinator, hass, description
):
    """A manual setting the valve never receives must not be offered."""
    coordinator = await make_coordinator()
    coordinator.device.manual_irrigation_mode = (
        "capacity" if "amount" in description.key else "duration"
    )

    await coordinator.async_start_manual_irrigation()
    before = read_fields(manual_payloads(hass)[-1])

    await SonoffSWVNumber(coordinator, description).async_set_native_value(15)
    await coordinator.async_start_manual_irrigation()
    after = read_fields(manual_payloads(hass)[-1])

    assert after != before, f"{description.name} has no effect on the valve"


async def test_manual_duration_is_the_one_sent(make_coordinator, hass):
    coordinator = await make_coordinator()
    coordinator.device.manual_irrigation_mode = "duration"
    duration = next(d for d in NUMBERS if d.key == "manual_irrigation_duration")

    await SonoffSWVNumber(coordinator, duration).async_set_native_value(15)
    await coordinator.async_start_manual_irrigation()

    assert manual_payloads(hass)[-1]["irrigation_duration"] == 15


async def test_entities_without_effect_are_removed_from_the_registry(make_coordinator, hass):
    coordinator = await make_coordinator()
    entry = ha_stubs.ConfigEntry("entry1")

    for key in ("manual_irrigation_total_duration", "manual_interval_duration"):
        hass.entity_registry.add(
            ha_stubs.RegistryEntry(
                entity_id=f"number.arrosage_test_{key}",
                unique_id=f"{IEEE}_{key}",
                platform="sonoff_swv",
                config_entry_id=entry.entry_id,
            )
        )

    await number_platform.async_setup_entry(hass, entry, lambda entities: None)

    left = sorted(e.entity_id for e in hass.entity_registry.entities.values())
    assert left == [], f"entities without effect still registered: {left}"


def test_example_dashboard_shows_the_real_manual_duration():
    text = EXAMPLE_DASHBOARD.read_text(encoding="utf-8")

    duration_rows = re.findall(r"number\.\w+_manual_(\w+)\n\s+name: Durata", text)
    assert duration_rows == ["irrigation_duration"], duration_rows
