"""Bug 5: renaming the valve in Zigbee2MQTT silently broke the integration.

The MQTT topics were built once, at setup time, from the Zigbee2MQTT
friendly name and a hard-coded "zigbee2mqtt" base topic. After a rename
in Zigbee2MQTT (or with another base topic) the integration listened and
wrote to topics nobody used: no state, and commands lost without error.

The valve is identified by its IEEE address, which never changes, and
Home Assistant's device registry follows the Zigbee2MQTT name.
"""

from __future__ import annotations

import ha_stubs

import custom_components.sonoff_swv as integration
from custom_components.sonoff_swv.config_flow import SonoffSWVConfigFlow
from custom_components.sonoff_swv.const import DOMAIN

from conftest import IEEE

OLD_NAME = "Arrosage Balcon"
NEW_NAME = "Arrosage Balcon Salon"


def z2m_device(hass, name: str) -> ha_stubs.DeviceEntry:
    """The valve as Home Assistant's MQTT integration registers it."""
    return hass.device_registry.add(
        ha_stubs.DeviceEntry(
            id="device1",
            identifiers={("mqtt", f"zigbee2mqtt_{IEEE}")},
            name=name,
        )
    )


def config_entry(hass, options: dict | None = None) -> ha_stubs.ConfigEntry:
    entry = ha_stubs.ConfigEntry(
        "entry1",
        data={"device_name": OLD_NAME, "ieee": IEEE},
        options=options,
        title=OLD_NAME,
    )
    hass.config_entries.entries.append(entry)
    return entry


async def set_up(hass, entry):
    await integration.async_setup(hass, {})
    assert await integration.async_setup_entry(hass, entry)
    return hass.data[DOMAIN][entry.entry_id]


async def test_setup_uses_the_current_zigbee2mqtt_name(hass):
    z2m_device(hass, NEW_NAME)  # renamed in Zigbee2MQTT since the valve was added
    entry = config_entry(hass)

    coordinator = await set_up(hass, entry)
    await coordinator.publish_attribute("child_lock")

    assert hass.mqtt_subscriptions[-1][0] == f"zigbee2mqtt/{NEW_NAME}"
    assert hass.mqtt_published[-1][0] == f"zigbee2mqtt/{NEW_NAME}/set"
    assert entry.data["device_name"] == NEW_NAME


async def test_rename_while_running_reloads_the_valve(hass):
    device = z2m_device(hass, OLD_NAME)
    entry = config_entry(hass)
    await set_up(hass, entry)

    device.name = NEW_NAME
    hass.bus.async_fire(
        ha_stubs.EVENT_DEVICE_REGISTRY_UPDATED,
        {"action": "update", "device_id": device.id, "changes": {"name": OLD_NAME}},
    )
    await hass.async_block_till_done()

    assert entry.entry_id in hass.config_entries.reloads, (
        "the rename is not picked up: topics still use the old name"
    )


async def test_other_base_topic(hass):
    z2m_device(hass, OLD_NAME)
    entry = config_entry(hass, options={"base_topic": "z2m"})

    coordinator = await set_up(hass, entry)
    await coordinator.publish_attribute("child_lock")

    assert hass.mqtt_subscriptions[-1][0] == f"z2m/{OLD_NAME}"
    assert hass.mqtt_published[-1][0] == f"z2m/{OLD_NAME}/set"


async def test_base_topic_can_be_changed_in_the_options(hass):
    assert hasattr(SonoffSWVConfigFlow, "async_get_options_flow"), (
        "no option to set the Zigbee2MQTT base topic"
    )

    entry = config_entry(hass)
    flow = SonoffSWVConfigFlow.async_get_options_flow(entry)
    flow.hass = hass
    flow.config_entry = entry

    form = await flow.async_step_init()
    assert form["type"] == "form"

    result = await flow.async_step_init({"base_topic": " z2m/ "})
    assert result == {"type": "create_entry", "title": "", "data": {"base_topic": "z2m"}}

    bad = await flow.async_step_init({"base_topic": "z2m/#"})
    assert bad["errors"] == {"base_topic": "invalid_base_topic"}
