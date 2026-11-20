"""Bug 3: next irrigation wrong for odd/even days and across a clock change.

- Plans repeating on odd or even days of the month (offered by the
  "Irrigation plan loop type" select) had no next run at all: no next
  irrigation, no warning, no weather check, and a false "plans not
  aligned" warning.
- Future runs were computed with today's UTC offset. On the evening
  before the change to summer time, a 07:00 run was announced at 08:00,
  so the warning and anything triggered "before the next irrigation"
  came an hour late.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import ha_stubs

from custom_components.sonoff_swv import coordinator as coordinator_module
from custom_components.sonoff_swv import sensor as sensor_module
from custom_components.sonoff_swv.next_irrigation import format_plan_line, next_run
from custom_components.sonoff_swv.sensor import SENSORS, SonoffSWVSensor

PARIS = ZoneInfo("Europe/Paris")


def plan(loop: str, **extra) -> dict:
    data = {
        "plan_index": 0,
        "enable_state": True,
        "loop_type_mode": loop,
        "loop_type_interval_days": 1,
        "loop_type_week_days": {},
        "enable_date": "2027-01-01",
        "start_time": "07:00",
        "irrigation_mode": "capacity",
        "irrigation_amount": 20,
        "irrigation_amount_unit": "liter",
        "fail_safe": 30,
        "create_datetime": "2027-01-01T12:00:00+01:00",
    }
    data.update(extra)
    return data


def paris(*args) -> datetime:
    return datetime(*args, tzinfo=PARIS)


# --- odd and even days ----------------------------------------------------


@pytest.mark.parametrize(
    ("loop", "now", "expected"),
    [
        ("odd_days", paris(2027, 5, 30, 10, 0), paris(2027, 5, 31, 7, 0)),
        ("odd_days", paris(2027, 5, 31, 8, 0), paris(2027, 6, 1, 7, 0)),
        ("even_days", paris(2027, 5, 31, 8, 0), paris(2027, 6, 2, 7, 0)),
        ("even_days", paris(2027, 6, 2, 6, 0), paris(2027, 6, 2, 7, 0)),
    ],
)
def test_odd_and_even_days_have_a_next_run(loop, now, expected):
    assert next_run(plan(loop), now) == expected


def test_odd_and_even_days_are_described_as_such():
    now = paris(2027, 5, 30, 10, 0)

    odd = format_plan_line(plan("odd_days"), now, lang="en")
    even = format_plan_line(plan("even_days"), now, lang="en")

    assert odd != even
    assert "every 1 d" not in odd


# --- change to summer time --------------------------------------------------


class FrozenDatetime(datetime):
    """datetime.now() as on a Home Assistant box whose clock is in Paris."""

    @classmethod
    def now(cls, tz=None):
        frozen = ha_stubs.clock.now()
        if tz is None:
            return frozen.replace(tzinfo=None)
        return frozen.astimezone(tz)


@pytest.fixture
def evening_before_summer_time(monkeypatch):
    """Saturday 27 March 2027, 20:00 in Paris; clocks go forward that night."""
    monkeypatch.setenv("TZ", "Europe/Paris")
    time.tzset()
    ha_stubs.clock.freeze(paris(2027, 3, 27, 20, 0))
    monkeypatch.setattr(sensor_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(coordinator_module, "datetime", FrozenDatetime)
    yield
    monkeypatch.undo()
    time.tzset()


def daily_plan() -> dict:
    return plan("day_interval", create_datetime="2027-03-01T12:00:00+01:00")


async def test_next_irrigation_across_the_clock_change(
    make_coordinator, evening_before_summer_time
):
    coordinator = await make_coordinator()
    coordinator.data["irrigation_plans"] = {"0": daily_plan()}

    description = next(d for d in SENSORS if d.key == "irrigation_next_event")
    value = SonoffSWVSensor(coordinator, description).native_value

    assert value == paris(2027, 3, 28, 7, 0), (
        f"announced {value.isoformat()}, the valve starts at 07:00 summer time"
    )


async def test_warning_across_the_clock_change(make_coordinator, hass, evening_before_summer_time):
    coordinator = await make_coordinator()
    coordinator.data["irrigation_plans"] = {"0": daily_plan()}
    coordinator.data["notifications"] = {
        "channel": "app",
        "target": "notify.mobile_app_phone",
        "plan_warning": True,
        "warning_minutes": 15,
    }

    coordinator._reschedule_warning()

    fire_times = [t.when for t in hass.active_timers()]
    assert paris(2027, 3, 28, 6, 45) in fire_times, (
        f"warning planned at {[t.isoformat() for t in fire_times]}"
    )
