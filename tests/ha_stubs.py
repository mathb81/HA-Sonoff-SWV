"""Minimal stand-ins for the parts of Home Assistant the integration uses.

The tests check the integration's own logic (what it publishes, stores and
shows), not Home Assistant itself, so they do not need a Home Assistant
install: these stubs are registered in ``sys.modules`` before the
integration is imported. They mimic the real API closely enough for that
purpose, and they record what the integration does (MQTT publishes, timers,
notifications, storage writes) so that tests can assert on it.

Time is controlled with ``clock``: ``dt_util.now()`` returns the real time
unless a test freezes it, and timers only fire when a test calls
``hass.async_fire_time_changed(...)``.
"""

from __future__ import annotations

import asyncio
import copy
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Generic, TypeVar
from zoneinfo import ZoneInfo

_T = TypeVar("_T")


# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------


class _Opaque:
    """Stand-in for enums and constants the tests never look at."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, item: str) -> Any:
        if item.startswith("__"):
            raise AttributeError(item)
        return f"{self._name}.{item}"

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def __repr__(self) -> str:
        return self._name


def _module(name: str, package: bool = False, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    if package:
        module.__path__ = []
    module.__dict__.update(attrs)

    def __getattr__(item: str) -> Any:
        if item.startswith("__"):
            raise AttributeError(item)
        return _Opaque(f"{name}.{item}")

    module.__getattr__ = __getattr__
    return module


def callback(func):
    """homeassistant.core.callback: a marker only."""
    return func


# --------------------------------------------------------------------------
# Clock and timers
# --------------------------------------------------------------------------


class Clock:
    """Controls dt_util.now(). Real time unless frozen by a test."""

    def __init__(self) -> None:
        self.frozen: datetime | None = None
        self.time_zone: tzinfo = ZoneInfo("Europe/Paris")

    def now(self) -> datetime:
        if self.frozen is not None:
            return self.frozen.astimezone(self.time_zone)
        return datetime.now(self.time_zone)

    def freeze(self, value: datetime) -> None:
        self.frozen = value

    def reset(self) -> None:
        self.frozen = None
        self.time_zone = ZoneInfo("Europe/Paris")


clock = Clock()


@dataclass
class Timer:
    when: datetime
    action: Any
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


def _register_timer(hass: "FakeHass", when: datetime, action: Any):
    timer = Timer(when, action)
    hass.timers.append(timer)
    return timer.cancel


def async_track_point_in_time(hass, action, point_in_time):
    return _register_timer(hass, point_in_time, action)


def async_call_later(hass, delay, action):
    seconds = delay.total_seconds() if isinstance(delay, timedelta) else delay
    return _register_timer(hass, clock.now() + timedelta(seconds=seconds), action)


def async_track_state_change_event(hass, entity_ids, action):
    return lambda: None


# --------------------------------------------------------------------------
# Registries
# --------------------------------------------------------------------------


@dataclass
class RegistryEntry:
    entity_id: str
    unique_id: str
    platform: str
    domain: str = ""
    config_entry_id: str | None = None
    device_id: str | None = None
    name: str | None = None
    original_name: str | None = None

    def __post_init__(self) -> None:
        if not self.domain:
            self.domain = self.entity_id.split(".", 1)[0]


class EntityRegistry:
    def __init__(self) -> None:
        self.entities: dict[str, RegistryEntry] = {}

    def add(self, entry: RegistryEntry) -> RegistryEntry:
        self.entities[entry.entity_id] = entry
        return entry

    def async_get(self, entity_id: str) -> RegistryEntry | None:
        return self.entities.get(entity_id)

    def async_get_entity_id(self, domain: str, platform: str, unique_id: str):
        for entry in self.entities.values():
            if (
                entry.domain == domain
                and entry.platform == platform
                and entry.unique_id == unique_id
            ):
                return entry.entity_id
        return None

    def async_remove(self, entity_id: str) -> None:
        self.entities.pop(entity_id, None)


def async_entries_for_config_entry(registry: EntityRegistry, config_entry_id: str):
    return [
        entry
        for entry in registry.entities.values()
        if entry.config_entry_id == config_entry_id
    ]


@dataclass
class DeviceEntry:
    id: str
    identifiers: set = field(default_factory=set)
    name: str | None = None
    name_by_user: str | None = None


class DeviceRegistry:
    def __init__(self) -> None:
        self.devices: dict[str, DeviceEntry] = {}

    def add(self, entry: DeviceEntry) -> DeviceEntry:
        self.devices[entry.id] = entry
        return entry

    def async_get(self, device_id: str) -> DeviceEntry | None:
        return self.devices.get(device_id)

    def async_get_device(self, identifiers=None, connections=None):
        for entry in self.devices.values():
            if identifiers and set(identifiers) & set(entry.identifiers):
                return entry
        return None


EVENT_DEVICE_REGISTRY_UPDATED = "device_registry_updated"


class DeviceInfo(dict):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


# --------------------------------------------------------------------------
# Hass, bus, config entries
# --------------------------------------------------------------------------


class Event:
    def __init__(self, event_type: str, data: dict | None = None) -> None:
        self.event_type = event_type
        self.data = data or {}


class Bus:
    def __init__(self, hass: "FakeHass") -> None:
        self._hass = hass
        self.listeners: list[tuple[str, Any, Any]] = []

    def async_listen(self, event_type, listener, event_filter=None, run_immediately=None):
        item = (event_type, listener, event_filter)
        self.listeners.append(item)

        def remove() -> None:
            if item in self.listeners:
                self.listeners.remove(item)

        return remove

    def async_listen_once(self, event_type, listener):
        return self.async_listen(event_type, listener)

    def async_fire(self, event_type: str, data: dict | None = None) -> None:
        event = Event(event_type, data)
        for listened, listener, event_filter in list(self.listeners):
            if listened != event_type:
                continue
            if event_filter is not None and not event_filter(event.data):
                continue
            result = listener(event)
            if asyncio.iscoroutine(result):
                self._hass.async_create_task(result)


class ConfigEntry:
    def __init__(
        self,
        entry_id: str = "entry1",
        data: dict | None = None,
        options: dict | None = None,
        title: str = "",
        domain: str = "sonoff_swv",
    ) -> None:
        self.entry_id = entry_id
        self.data = dict(data or {})
        self.options = dict(options or {})
        self.title = title
        self.domain = domain
        self._on_unload: list[Any] = []
        self.update_listeners: list[Any] = []

    def async_on_unload(self, func) -> None:
        self._on_unload.append(func)

    def add_update_listener(self, listener):
        self.update_listeners.append(listener)
        return lambda: self.update_listeners.remove(listener)


class ConfigEntries:
    def __init__(self, hass: "FakeHass") -> None:
        self._hass = hass
        self.entries: list[ConfigEntry] = []
        self.forwarded: list[tuple[str, list[str]]] = []
        self.reloads: list[str] = []
        self.updates: list[tuple[str, dict]] = []

    def async_entries(self, domain: str | None = None):
        return [e for e in self.entries if domain is None or e.domain == domain]

    def async_get_entry(self, entry_id: str):
        for entry in self.entries:
            if entry.entry_id == entry_id:
                return entry
        return None

    async def async_forward_entry_setups(self, entry, platforms) -> None:
        self.forwarded.append((entry.entry_id, list(platforms)))

    async def async_unload_platforms(self, entry, platforms) -> bool:
        return True

    def async_update_entry(self, entry, **changes) -> bool:
        for key, value in changes.items():
            setattr(entry, key, value)
        self.updates.append((entry.entry_id, changes))
        return True

    def async_schedule_reload(self, entry_id: str) -> None:
        self.reloads.append(entry_id)

    async def async_reload(self, entry_id: str) -> bool:
        self.reloads.append(entry_id)
        return True


class Services:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def async_call(self, domain, service, data=None, blocking=False, **kwargs):
        self.calls.append((domain, service, dict(data or {})))


class States:
    def __init__(self) -> None:
        self._states: dict[str, Any] = {}

    def get(self, entity_id: str):
        return self._states.get(entity_id)


class FakeHass:
    """The subset of HomeAssistant used by the integration."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.config = types.SimpleNamespace(language="en", time_zone="Europe/Paris")
        self.bus = Bus(self)
        self.config_entries = ConfigEntries(self)
        self.services = Services()
        self.states = States()
        self.is_running = True
        self.timers: list[Timer] = []
        self.tasks: list[asyncio.Task] = []
        self.mqtt_published: list[tuple[str, Any]] = []
        self.mqtt_subscriptions: list[tuple[str, Any]] = []
        self.notifications: dict[str, dict[str, Any]] = {}
        self.entity_registry = EntityRegistry()
        self.device_registry = DeviceRegistry()
        self.storage: dict[str, Any] = {}
        self.storage_writes: list[str] = []
        self.storage_delayed: dict[str, Any] = {}

    # Tasks ---------------------------------------------------------------

    def async_create_task(self, coro, name: str | None = None, eager_start: bool = True):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task

    def async_create_background_task(self, coro, name: str | None = None, eager_start: bool = True):
        return self.async_create_task(coro, name)

    async def async_block_till_done(self) -> None:
        for _ in range(50):
            pending = [task for task in self.tasks if not task.done()]
            if not pending:
                await asyncio.sleep(0)
                if not [task for task in self.tasks if not task.done()]:
                    return
                continue
            await asyncio.gather(*pending)

    # Time ----------------------------------------------------------------

    def active_timers(self) -> list[Timer]:
        return [timer for timer in self.timers if not timer.cancelled]

    def async_fire_time_changed(self, when: datetime) -> None:
        """Move the clock to ``when`` and run the timers that are due."""
        clock.freeze(when)
        while True:
            due = sorted(
                (t for t in self.active_timers() if t.when <= when),
                key=lambda t: t.when,
            )
            if not due:
                return
            timer = due[0]
            timer.cancelled = True
            result = timer.action(timer.when)
            if asyncio.iscoroutine(result):
                self.async_create_task(result)


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


class Store:
    def __init__(self, hass: FakeHass, version: int, key: str, **kwargs: Any) -> None:
        self.hass = hass
        self.key = key

    async def async_load(self):
        return copy.deepcopy(self.hass.storage.get(self.key))

    async def async_save(self, data) -> None:
        self.hass.storage[self.key] = copy.deepcopy(data)
        self.hass.storage_writes.append(self.key)

    def async_delay_save(self, data_func, delay: float = 0) -> None:
        self.hass.storage_delayed[self.key] = data_func

    async def async_remove(self) -> None:
        self.hass.storage.pop(self.key, None)


async def flush_delayed_saves(hass: FakeHass) -> None:
    """What Home Assistant does when a delayed save comes due."""
    for key, data_func in list(hass.storage_delayed.items()):
        hass.storage[key] = copy.deepcopy(data_func())
        hass.storage_writes.append(key)
    hass.storage_delayed.clear()


# --------------------------------------------------------------------------
# MQTT and notifications
# --------------------------------------------------------------------------


async def mqtt_async_publish(hass, topic, payload, qos=0, retain=False, encoding="utf-8"):
    hass.mqtt_published.append((topic, payload))


async def mqtt_async_subscribe(hass, topic, msg_callback, qos=0, encoding="utf-8"):
    item = (topic, msg_callback)
    hass.mqtt_subscriptions.append(item)
    return lambda: hass.mqtt_subscriptions.remove(item)


def persistent_notification_create(hass, message, title=None, notification_id=None):
    hass.notifications[notification_id or str(len(hass.notifications))] = {
        "message": message,
        "title": title,
    }


def persistent_notification_dismiss(hass, notification_id):
    hass.notifications.pop(notification_id, None)


# --------------------------------------------------------------------------
# Coordinator and entities
# --------------------------------------------------------------------------


class DataUpdateCoordinator(Generic[_T]):
    def __init__(self, hass, logger, *, name, update_interval=None, **kwargs) -> None:
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data: Any = None
        self.last_update_success = True
        self._listeners: list[Any] = []
        self.update_count = 0

    def async_add_listener(self, update_callback, context=None):
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    def async_update_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    def async_set_updated_data(self, data) -> None:
        self.data = data
        self.last_update_success = True
        self.update_count += 1
        self.async_update_listeners()


class Entity:
    entity_description: Any = None
    entity_id: str | None = None
    hass: Any = None
    _attr_unique_id: str | None = None
    _attr_name: str | None = None
    _attr_icon: str | None = None
    _attr_has_entity_name: bool = False
    _attr_available: bool = True

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        if self._attr_name is not None:
            return self._attr_name
        if self.entity_description is not None:
            return self.entity_description.name
        return None

    @property
    def available(self) -> bool:
        return self._attr_available

    def async_write_ha_state(self) -> None:
        self.state_writes = getattr(self, "state_writes", 0) + 1

    async def async_added_to_hass(self) -> None:
        return None

    def async_on_remove(self, func) -> None:
        return None


class CoordinatorEntity(Entity, Generic[_T]):
    def __init__(self, coordinator, context=None) -> None:
        self.coordinator = coordinator
        self.hass = coordinator.hass

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


@dataclass(frozen=True, kw_only=True)
class EntityDescription:
    key: str
    name: Any = None
    icon: str | None = None
    device_class: Any = None
    entity_category: Any = None
    translation_key: str | None = None
    entity_registry_enabled_default: bool = True
    has_entity_name: bool = False
    unit_of_measurement: str | None = None


@dataclass(frozen=True, kw_only=True)
class NumberEntityDescription(EntityDescription):
    native_min_value: float | None = None
    native_max_value: float | None = None
    native_step: float | None = None
    native_unit_of_measurement: str | None = None
    mode: Any = None


@dataclass(frozen=True, kw_only=True)
class SensorEntityDescription(EntityDescription):
    native_unit_of_measurement: str | None = None
    state_class: Any = None
    suggested_display_precision: int | None = None
    options: list | None = None


@dataclass(frozen=True, kw_only=True)
class SelectEntityDescription(EntityDescription):
    options: Any = None


class NumberEntity(Entity):
    pass


class SensorEntity(Entity):
    pass


class SelectEntity(Entity):
    _attr_options: list[str] = []
    _attr_current_option: str | None = None

    @property
    def options(self):
        return self._attr_options

    @property
    def current_option(self):
        return self._attr_current_option


class SwitchEntity(Entity):
    pass


class ButtonEntity(Entity):
    pass


class TimeEntity(Entity):
    pass


class DateEntity(Entity):
    pass


class DateTimeEntity(Entity):
    pass


class TextEntity(Entity):
    pass


class BinarySensorEntity(Entity):
    pass


# --------------------------------------------------------------------------
# Config flow
# --------------------------------------------------------------------------


class FlowHandler:
    hass: Any = None

    def async_show_form(self, *, step_id, data_schema=None, errors=None, **kwargs):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
        }

    def async_create_entry(self, *, title="", data=None, **kwargs):
        return {"type": "create_entry", "title": title, "data": data or {}}

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}


class ConfigFlow(FlowHandler):
    def __init_subclass__(cls, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.DOMAIN = domain

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self) -> None:
        return None


class OptionsFlow(FlowHandler):
    config_entry: Any = None


class OptionsFlowWithReload(OptionsFlow):
    """Reloads the entry after the options change (real HA does it itself)."""


# --------------------------------------------------------------------------
# voluptuous (only what the config flow builds)
# --------------------------------------------------------------------------


class _Marker:
    def __init__(self, schema, default=None, description=None, msg=None) -> None:
        self.schema = schema
        self.default = default if callable(default) or default is None else (lambda: default)

    def __hash__(self) -> int:
        return hash(self.schema)

    def __eq__(self, other) -> bool:
        return getattr(other, "schema", other) == self.schema

    def __str__(self) -> str:
        return str(self.schema)


class Required(_Marker):
    pass


class Optional(_Marker):
    pass


class Schema:
    def __init__(self, schema, extra=None) -> None:
        self.schema = schema

    def __call__(self, data):
        return data


# --------------------------------------------------------------------------
# Installation
# --------------------------------------------------------------------------


def _er_async_get(hass: FakeHass) -> EntityRegistry:
    return hass.entity_registry


def _dr_async_get(hass: FakeHass) -> DeviceRegistry:
    return hass.device_registry


def install() -> None:
    """Register the stub modules in sys.modules (idempotent)."""

    if getattr(sys.modules.get("homeassistant"), "__swv_stub__", False):
        return

    dt_util = _module(
        "homeassistant.util.dt",
        now=lambda time_zone=None: clock.now(),
        utcnow=lambda: clock.now().astimezone(timezone.utc),
        get_default_time_zone=lambda: clock.time_zone,
        as_local=lambda value: value.astimezone(clock.time_zone),
        parse_datetime=lambda value: datetime.fromisoformat(value),
    )

    modules = {
        "homeassistant": _module("homeassistant", package=True, __swv_stub__=True),
        "homeassistant.core": _module(
            "homeassistant.core",
            HomeAssistant=FakeHass,
            callback=callback,
            Event=Event,
        ),
        "homeassistant.const": _module("homeassistant.const", PERCENTAGE="%"),
        "homeassistant.config_entries": _module(
            "homeassistant.config_entries",
            ConfigEntry=ConfigEntry,
            ConfigFlow=ConfigFlow,
            OptionsFlow=OptionsFlow,
            OptionsFlowWithReload=OptionsFlowWithReload,
            ConfigFlowResult=dict,
        ),
        "homeassistant.components": _module("homeassistant.components", package=True),
        "homeassistant.components.mqtt": _module(
            "homeassistant.components.mqtt",
            async_publish=mqtt_async_publish,
            async_subscribe=mqtt_async_subscribe,
            callback=callback,
        ),
        "homeassistant.components.persistent_notification": _module(
            "homeassistant.components.persistent_notification",
            async_create=persistent_notification_create,
            async_dismiss=persistent_notification_dismiss,
        ),
        "homeassistant.components.number": _module(
            "homeassistant.components.number",
            NumberEntity=NumberEntity,
            NumberEntityDescription=NumberEntityDescription,
        ),
        "homeassistant.components.sensor": _module(
            "homeassistant.components.sensor",
            SensorEntity=SensorEntity,
            SensorEntityDescription=SensorEntityDescription,
        ),
        "homeassistant.components.select": _module(
            "homeassistant.components.select",
            SelectEntity=SelectEntity,
            SelectEntityDescription=SelectEntityDescription,
        ),
        "homeassistant.components.switch": _module(
            "homeassistant.components.switch",
            SwitchEntity=SwitchEntity,
            SwitchEntityDescription=EntityDescription,
        ),
        "homeassistant.components.button": _module(
            "homeassistant.components.button",
            ButtonEntity=ButtonEntity,
            ButtonEntityDescription=EntityDescription,
        ),
        "homeassistant.components.time": _module(
            "homeassistant.components.time",
            TimeEntity=TimeEntity,
            TimeEntityDescription=EntityDescription,
        ),
        "homeassistant.components.date": _module(
            "homeassistant.components.date",
            DateEntity=DateEntity,
            DateEntityDescription=EntityDescription,
        ),
        "homeassistant.components.datetime": _module(
            "homeassistant.components.datetime",
            DateTimeEntity=DateTimeEntity,
            DateTimeEntityDescription=EntityDescription,
        ),
        "homeassistant.components.text": _module(
            "homeassistant.components.text",
            TextEntity=TextEntity,
            TextEntityDescription=EntityDescription,
        ),
        "homeassistant.components.binary_sensor": _module(
            "homeassistant.components.binary_sensor",
            BinarySensorEntity=BinarySensorEntity,
            BinarySensorEntityDescription=EntityDescription,
        ),
        "homeassistant.helpers": _module("homeassistant.helpers", package=True),
        "homeassistant.helpers.entity_platform": _module(
            "homeassistant.helpers.entity_platform",
            AddEntitiesCallback=Any,
        ),
        "homeassistant.helpers.event": _module(
            "homeassistant.helpers.event",
            async_track_point_in_time=async_track_point_in_time,
            async_call_later=async_call_later,
            async_track_state_change_event=async_track_state_change_event,
        ),
        "homeassistant.helpers.entity_registry": _module(
            "homeassistant.helpers.entity_registry",
            async_get=_er_async_get,
            async_entries_for_config_entry=async_entries_for_config_entry,
            RegistryEntry=RegistryEntry,
        ),
        "homeassistant.helpers.device_registry": _module(
            "homeassistant.helpers.device_registry",
            async_get=_dr_async_get,
            DeviceEntry=DeviceEntry,
            DeviceInfo=DeviceInfo,
            EVENT_DEVICE_REGISTRY_UPDATED=EVENT_DEVICE_REGISTRY_UPDATED,
        ),
        "homeassistant.helpers.update_coordinator": _module(
            "homeassistant.helpers.update_coordinator",
            DataUpdateCoordinator=DataUpdateCoordinator,
            CoordinatorEntity=CoordinatorEntity,
        ),
        "homeassistant.helpers.storage": _module(
            "homeassistant.helpers.storage",
            Store=Store,
        ),
        "homeassistant.helpers.config_validation": _module(
            "homeassistant.helpers.config_validation",
            config_entry_only_config_schema=lambda domain: None,
        ),
        "homeassistant.helpers.selector": _module("homeassistant.helpers.selector"),
        "homeassistant.util": _module("homeassistant.util", package=True, dt=dt_util),
        "homeassistant.util.dt": dt_util,
        "voluptuous": _module(
            "voluptuous",
            Schema=Schema,
            Required=Required,
            Optional=Optional,
        ),
    }

    # Parent packages expose their submodules as attributes, as real
    # imports do ("from homeassistant.components import mqtt").
    for name, module in modules.items():
        sys.modules[name] = module
        parent, _, child = name.rpartition(".")
        if parent in modules:
            setattr(modules[parent], child, module)
