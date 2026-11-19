"""Bug 6a: the storage file was rewritten for every message of the valve.

Every MQTT message (battery, flow, link quality...) rewrote the whole
storage file of the valve, history included: needless writes on the SD
card or SSD of Home Assistant, several per minute while watering. Home
Assistant's Store can group them (async_delay_save) and still writes
pending data when Home Assistant stops.
"""

from __future__ import annotations

import ha_stubs


async def test_many_messages_one_write(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    for level in range(80, 60, -1):
        coordinator.update_from_device({"battery": level, "linkquality": 120})
    await hass.async_block_till_done()

    immediate = len(hass.storage_writes)
    await ha_stubs.flush_delayed_saves(hass)

    assert immediate == 0, f"{immediate} writes for 20 messages"
    assert len(hass.storage_writes) == 1


async def test_latest_data_is_written(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    coordinator.update_from_device({"battery": 80})
    coordinator.update_from_device({"battery": 61})
    await hass.async_block_till_done()
    await ha_stubs.flush_delayed_saves(hass)

    stored = next(iter(hass.storage.values()))
    assert stored["device"]["battery"] == 61
