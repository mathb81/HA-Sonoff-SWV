"""Bug 1: a plan the valve never accepted was shown as saved.

Saving a plan publishes it to Zigbee2MQTT and immediately archives it as
the plan of that slot. Zigbee2MQTT drops the whole plan when one value is
out of range (it only logs an error), and a valve that does not answer
never stores it either: the integration still showed the plan, its next
run and the warning before it.

A plan only stays in the archive once it is confirmed, and the previous
plan comes back otherwise.

On real hardware (SWV-ZFE, captured on 2026-11-19) the valve does NOT send
an irrigation_plan_report after a write: the report only comes when the
valve rejoins the network, so it stayed frozen on a July plan while every
new plan was accepted. What does come back, within a second, is the
Zigbee2MQTT state echo of irrigation_plan_settings carrying the
create_datetime of the write; a write that Zigbee2MQTT rejects
("irrigation_plan_settings invalid irrigation_amount ...") produces no echo.
Both the echo and a matching report count as a confirmation.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import ha_stubs

from custom_components.sonoff_swv.button import BUTTONS, SonoffSWVButton
from custom_components.sonoff_swv.number import NUMBERS

SAVE_PLAN = next(d for d in BUTTONS if d.key == "irrigation_plan_settings")

WEEK = {
    "monday": True,
    "tuesday": False,
    "wednesday": True,
    "thursday": False,
    "friday": True,
    "saturday": False,
    "sunday": False,
}


def valve_report(plan_index: int, start_time: str, amount: int, created: str) -> dict:
    """An irrigation_plan_report as the valve sends it (capacity mode)."""
    return {
        "plan_index": plan_index,
        "enable_state": True,
        "loop_type_mode": "weekdays",
        "loop_type_interval_days": 0,
        "loop_type_week_days": dict(WEEK),
        "enable_date": "2026-11-19",
        "start_time": start_time,
        "irrigation_mode": "capacity",
        "irrigation_amount": amount,
        "irrigation_amount_unit": "liter",
        "irrigation_duration": 0,
        "irrigation_total_duration": 0,
        "interval_duration": 0,
        "fail_safe": 30,
        "create_datetime": created,
    }


async def save_plan_from_form(coordinator, plan_index: int, start_time: str, amount: int):
    """Fill the plan form as a user would, then press "save"."""
    await coordinator.async_load_plan_into_form(plan_index)

    device = coordinator.device
    device.irrigation_plan_index = plan_index
    device.irrigation_plan_enabled = True
    device.irrigation_plan_loop_type = "weekdays"
    for day, on in WEEK.items():
        setattr(device, f"irrigation_plan_{day}", on)
    device.irrigation_plan_start_time = start_time
    device.irrigation_plan_mode = "capacity"
    device.irrigation_plan_amount = amount
    device.irrigation_plan_amount_unit = "liter"
    device.irrigation_plan_fail_safe = 30

    await SonoffSWVButton(coordinator, SAVE_PLAN).async_press()


def archived(coordinator, plan_index: int) -> dict | None:
    return coordinator.data.get("irrigation_plans", {}).get(str(plan_index))


def later(minutes: int = 10):
    return ha_stubs.clock.now() + timedelta(minutes=minutes)


def test_plan_amount_cannot_be_zero():
    """Zigbee2MQTT accepts 1 to 10000 L: 0 made it drop the whole plan."""
    amount = next(d for d in NUMBERS if d.key == "irrigation_plan_amount")

    assert amount.native_min_value >= 1


async def test_plan_never_confirmed_by_the_valve_is_not_kept(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    # The valve stores plan 2 at 06:00, 10 L.
    coordinator.update_from_device(
        {"irrigation_plan_report": valve_report(2, "06:00", 10, "2026-11-01T20:00:00+01:00")}
    )

    await save_plan_from_form(coordinator, 2, "07:30", 25)
    assert hass.mqtt_published, "the plan must be published"

    # Nothing comes back from the valve.
    hass.async_fire_time_changed(later())
    await hass.async_block_till_done()

    plan = archived(coordinator, 2)
    assert plan is not None
    assert (plan["start_time"], plan["irrigation_amount"]) == ("06:00", 10), (
        "the plan the valve did not confirm is still shown as saved"
    )
    assert hass.notifications, "the user must be told that the plan was not saved"


async def test_new_plan_never_confirmed_disappears(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    await save_plan_from_form(coordinator, 4, "21:00", 15)

    hass.async_fire_time_changed(later())
    await hass.async_block_till_done()

    assert archived(coordinator, 4) is None, "an unconfirmed new plan is still listed"


async def test_cached_report_does_not_confirm_a_new_plan(make_coordinator, hass):
    """Zigbee2MQTT repeats the last report in every state message."""
    coordinator = await make_coordinator()
    await coordinator.async_start()

    old_report = valve_report(2, "06:00", 10, "2026-11-01T20:00:00+01:00")
    coordinator.update_from_device({"irrigation_plan_report": old_report})

    await save_plan_from_form(coordinator, 2, "06:00", 25)

    # A battery update carries the cached, older report of the same slot.
    coordinator.update_from_device({"battery": 80, "irrigation_plan_report": old_report})

    hass.async_fire_time_changed(later())
    await hass.async_block_till_done()

    assert archived(coordinator, 2)["irrigation_amount"] == 10


async def test_plan_confirmed_by_the_valve_is_kept(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    coordinator.update_from_device(
        {"irrigation_plan_report": valve_report(2, "06:00", 10, "2026-11-01T20:00:00+01:00")}
    )

    await save_plan_from_form(coordinator, 2, "07:30", 25)

    # The valve stores it and reports it.
    coordinator.update_from_device(
        {"irrigation_plan_report": valve_report(2, "07:30", 25, "2026-11-19T16:30:00+01:00")}
    )

    hass.async_fire_time_changed(later())
    await hass.async_block_till_done()

    plan = archived(coordinator, 2)
    assert (plan["start_time"], plan["irrigation_amount"]) == ("07:30", 25)
    assert not hass.notifications


async def test_pending_plan_is_still_checked_after_a_restart(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    coordinator.update_from_device(
        {"irrigation_plan_report": valve_report(2, "06:00", 10, "2026-11-01T20:00:00+01:00")}
    )
    await save_plan_from_form(coordinator, 2, "07:30", 25)
    await hass.async_block_till_done()

    # Home Assistant restarts before the valve answers.
    await coordinator.async_stop()
    restarted = await make_coordinator()
    await restarted.async_start()

    hass.async_fire_time_changed(later())
    await hass.async_block_till_done()

    assert archived(restarted, 2)["start_time"] == "06:00"


async def test_valve_reporting_other_settings_is_shown_and_flagged(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    await save_plan_from_form(coordinator, 3, "07:30", 25)

    # The valve answers for slot 3, but with other settings than the ones written.
    coordinator.update_from_device(
        {"irrigation_plan_report": valve_report(3, "07:30", 30, "2026-11-19T16:30:00+01:00")}
    )

    hass.async_fire_time_changed(later())
    await hass.async_block_till_done()

    assert archived(coordinator, 3)["irrigation_amount"] == 30, "the valve's own plan wins"
    assert hass.notifications, "the user must be told that the valve kept other settings"


def settings_echo(written: dict) -> dict:
    """The irrigation_plan_settings Zigbee2MQTT publishes after an accepted write."""
    echo = dict(written)
    echo.pop("source", None)
    echo.pop("updated_at", None)
    return echo


def written_plan(coordinator, plan_index: int) -> dict:
    return coordinator.data["plan_pending"][str(plan_index)]["written"]


async def test_plan_accepted_by_zigbee2mqtt_is_kept(make_coordinator, hass):
    """Captured 2026-11-19: the echo comes back, the report stays frozen."""
    coordinator = await make_coordinator()
    await coordinator.async_start()

    stale_report = valve_report(0, "19:00", 75, "2026-07-11T23:57:00+02:00")
    coordinator.update_from_device({"irrigation_plan_report": stale_report})

    await save_plan_from_form(coordinator, 0, "18:00", 1)
    echo = settings_echo(written_plan(coordinator, 0))

    # Zigbee2MQTT accepts the write: its state echoes the plan just written,
    # next to the cached report the valve sent months ago.
    coordinator.update_from_device(
        {"irrigation_plan_settings": echo, "irrigation_plan_report": stale_report}
    )

    hass.async_fire_time_changed(later())
    await hass.async_block_till_done()

    plan = archived(coordinator, 0)
    assert (plan["start_time"], plan["irrigation_amount"]) == ("18:00", 1), (
        "a plan Zigbee2MQTT accepted is shown as not saved"
    )
    assert not hass.notifications


async def test_cached_settings_echo_does_not_confirm_a_new_plan(make_coordinator, hass):
    """Every state message repeats the last echo: only the echo of this write counts."""
    coordinator = await make_coordinator()
    await coordinator.async_start()

    await save_plan_from_form(coordinator, 0, "18:00", 5)
    first_echo = settings_echo(written_plan(coordinator, 0))
    coordinator.update_from_device({"irrigation_plan_settings": first_echo})

    # A second write of the same slot that Zigbee2MQTT rejects: no new echo,
    # the state keeps repeating the first one.
    await asyncio.sleep(1.1)  # create_datetime has a one-second resolution
    await save_plan_from_form(coordinator, 0, "18:00", 0)
    written = written_plan(coordinator, 0)
    assert written["create_datetime"] != first_echo["create_datetime"]

    coordinator.update_from_device({"battery": 80, "irrigation_plan_settings": first_echo})

    hass.async_fire_time_changed(later())
    await hass.async_block_till_done()

    assert archived(coordinator, 0)["irrigation_amount"] == 5
    assert hass.notifications, "the user must be told that the plan was not saved"


async def test_echo_of_another_slot_does_not_confirm(make_coordinator, hass):
    coordinator = await make_coordinator()
    await coordinator.async_start()

    await save_plan_from_form(coordinator, 2, "07:30", 25)
    echo = settings_echo(written_plan(coordinator, 2))
    echo["plan_index"] = 3

    coordinator.update_from_device({"irrigation_plan_settings": echo})

    hass.async_fire_time_changed(later())
    await hass.async_block_till_done()

    assert archived(coordinator, 2) is None
