"""Every module of the integration can be imported."""

from __future__ import annotations

import importlib
import pkgutil

import custom_components.sonoff_swv as integration


def test_all_modules_import():
    names = [
        module.name
        for module in pkgutil.walk_packages(
            integration.__path__,
            prefix=f"{integration.__name__}.",
        )
    ]

    assert "custom_components.sonoff_swv.coordinator" in names
    assert "custom_components.sonoff_swv.models.device" in names

    for name in names:
        importlib.import_module(name)


async def test_coordinator_starts_and_publishes(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    assert hass.mqtt_subscriptions[0][0] == "zigbee2mqtt/Arrosage Test"

    await coordinator.publish_attribute("child_lock")

    assert hass.mqtt_published[-1][0] == "zigbee2mqtt/Arrosage Test/set"
