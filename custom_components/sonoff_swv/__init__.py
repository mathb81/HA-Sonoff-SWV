from __future__ import annotations
import logging
import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from .config_flow import MQTT_DEVICE_REGISTRY_DOMAIN, ZIGBEE2MQTT_IDENTIFIER_PREFIX
from .const import CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC, DOMAIN
from .coordinator import SonoffSWVCoordinator
from .storage import async_remove_storage

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    "sensor",
    "number",
    "switch",
    "time",
    "date",
    "select",
    "button",
    "binary_sensor",
    "text",
]

async def async_setup(
    hass: HomeAssistant,
    config,
) -> bool:
    """Set up Sonoff SWV."""
    hass.data.setdefault(
        DOMAIN,
        {},
    )
    return True
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up Sonoff SWV from config entry."""
    _LOGGER.info(
        "Setting up Sonoff SWV for device %s",
        entry.data,
    )
    coordinator = SonoffSWVCoordinator(
        hass,
        entry.entry_id,
        _async_current_device_name(hass, entry),
        entry.data.get("ieee"),
        entry.options.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC),
    )
    await coordinator.async_initialize()
    hass.data[DOMAIN][
        entry.entry_id
    ] = coordinator
    await coordinator.async_start()
    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )
    _async_follow_renames(hass, entry, coordinator.device_name)
    return True


def _async_z2m_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dr.DeviceEntry | None:
    """The valve in the device registry, found by its IEEE address."""
    ieee = entry.data.get("ieee")
    if not ieee:
        return None
    return dr.async_get(hass).async_get_device(
        identifiers={
            (MQTT_DEVICE_REGISTRY_DOMAIN, f"{ZIGBEE2MQTT_IDENTIFIER_PREFIX}{ieee}")
        }
    )


def _async_current_device_name(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> str:
    """Current Zigbee2MQTT name of the valve.

    The MQTT topics use the Zigbee2MQTT friendly name, which can be changed
    in Zigbee2MQTT at any time; the device registry follows it. The name
    stored in the entry is only a fallback.
    """
    stored = entry.data["device_name"]
    device = _async_z2m_device(hass, entry)
    current = device.name if device is not None and device.name else stored

    if current != stored:
        _LOGGER.info(
            "Valve renamed in Zigbee2MQTT: '%s' is now '%s'",
            stored,
            current,
        )
        changes = {"data": {**entry.data, "device_name": current}}
        if entry.title == stored:
            changes["title"] = current
        hass.config_entries.async_update_entry(entry, **changes)

    return current


def _async_follow_renames(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_name: str,
) -> None:
    """Reload the valve when Zigbee2MQTT renames it."""
    device = _async_z2m_device(hass, entry)
    if device is None:
        return

    @callback
    def _device_updated(event: Event) -> None:
        if event.data.get("action") != "update":
            return
        if event.data.get("device_id") != device.id:
            return
        if "name" not in event.data.get("changes", {}):
            return
        current = dr.async_get(hass).async_get(device.id)
        if current is None or not current.name or current.name == device_name:
            return
        hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))

    entry.async_on_unload(
        hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _device_updated)
    )
async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload Sonoff SWV."""
    coordinator = hass.data[DOMAIN][
        entry.entry_id
    ]
    await coordinator.async_stop()
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
    if unload_ok:
        hass.data[DOMAIN].pop(
            entry.entry_id
        )
    return unload_ok
async def async_remove_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Delete the stored data of a removed valve."""
    await async_remove_storage(
        hass,
        entry.entry_id,
    )
