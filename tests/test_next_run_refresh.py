"""Bug 4: "next irrigation" stayed on a time already past.

The next irrigation and the plans summary are computed from the clock,
but Home Assistant only saw them again when the valve sent a message.
When a run is skipped (rain delay, valve out of reach) and the valve
stays silent, the sensor kept showing a time already past, so anything
triggered from it (weather check, reminders) missed the following run.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import ha_stubs

from custom_components.sonoff_swv import coordinator as coordinator_module
from custom_components.sonoff_swv import sensor as sensor_module
from custom_components.sonoff_swv.sensor import SENSORS, SonoffSWVSensor

PARIS = ZoneInfo("Europe/Paris")


def paris(*args) -> datetime:
    return datetime(*args, tzinfo=PARIS)


DAILY_AT_7 = {
    "plan_index": 0,
    "enable_state": True,
    "loop_type_mode": "day_interval",
    "loop_type_interval_days": 1,
    "loop_type_week_days": {},
    "enable_date": "2027-06-01",
    "start_time": "07:00",
    "irrigation_mode": "capacity",
    "irrigation_amount": 20,
    "irrigation_amount_unit": "liter",
    "fail_safe": 30,
    "create_datetime": "2027-06-01T12:00:00+02:00",
}


class FrozenDatetime(datetime):
    """datetime.now() as on a Home Assistant box whose clock is in Paris."""

    @classmethod
    def now(cls, tz=None):
        frozen = ha_stubs.clock.now()
        if tz is None:
            return frozen.replace(tzinfo=None)
        return frozen.astimezone(tz)


@pytest.fixture(autouse=True)
def _paris_clock(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Paris")
    time.tzset()
    ha_stubs.clock.freeze(paris(2027, 6, 10, 6, 58))
    monkeypatch.setattr(sensor_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(coordinator_module, "datetime", FrozenDatetime)
    yield
    monkeypatch.undo()
    time.tzset()


class RecordingSensor(SonoffSWVSensor):
    """Records the value Home Assistant gets each time the state is written."""

    def async_write_ha_state(self) -> None:
        self.written = getattr(self, "written", []) + [self.native_value]


async def next_event_sensor(make_coordinator):
    coordinator = await make_coordinator()
    coordinator.data["irrigation_plans"] = {"0": dict(DAILY_AT_7)}

    description = next(d for d in SENSORS if d.key == "irrigation_next_event")
    sensor = RecordingSensor(coordinator, description)
    coordinator.async_add_listener(sensor._handle_coordinator_update)

    await coordinator.async_start()
    coordinator.async_set_updated_data(coordinator.data)
    return coordinator, sensor


async def test_next_irrigation_moves_on_without_any_message(make_coordinator, hass):
    coordinator, sensor = await next_event_sensor(make_coordinator)
    assert sensor.written[-1] == paris(2027, 6, 10, 7, 0)

    # 07:00 passes; the run is skipped and the valve sends nothing.
    hass.async_fire_time_changed(paris(2027, 6, 10, 7, 5))
    await hass.async_block_till_done()

    assert sensor.written[-1] == paris(2027, 6, 11, 7, 0), (
        f"Home Assistant still shows {sensor.written[-1].isoformat()}"
    )


async def test_it_keeps_moving_on_day_after_day(make_coordinator, hass):
    coordinator, sensor = await next_event_sensor(make_coordinator)

    for day in (10, 11, 12):
        hass.async_fire_time_changed(paris(2027, 6, day, 7, 5))
        await hass.async_block_till_done()

    assert sensor.written[-1] == paris(2027, 6, 13, 7, 0)


async def test_no_timer_left_after_unload(make_coordinator, hass):
    coordinator, _sensor = await next_event_sensor(make_coordinator)

    await coordinator.async_stop()

    assert hass.active_timers() == []
