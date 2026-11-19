"""Shared fixtures. Home Assistant is replaced by the stubs in ha_stubs.py."""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import ha_stubs  # noqa: E402

ha_stubs.install()

IEEE = "0xa4c138142f74ffff"
DEVICE_NAME = "Arrosage Test"


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run ``async def`` tests in a fresh event loop (no plugin needed)."""
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        kwargs = {
            name: pyfuncitem.funcargs[name]
            for name in pyfuncitem._fixtureinfo.argnames
        }
        asyncio.run(pyfuncitem.obj(**kwargs))
        return True
    return None


@pytest.fixture(autouse=True)
def _reset_clock():
    ha_stubs.clock.reset()
    yield
    ha_stubs.clock.reset()


@pytest.fixture
def hass():
    return ha_stubs.FakeHass()


@pytest.fixture
def make_coordinator(hass):
    """Build and initialise a coordinator for one valve."""

    async def _make(device_name: str = DEVICE_NAME, ieee: str = IEEE, entry_id: str = "entry1"):
        from custom_components.sonoff_swv.const import DOMAIN
        from custom_components.sonoff_swv.coordinator import SonoffSWVCoordinator

        coordinator = SonoffSWVCoordinator(hass, entry_id, device_name, ieee)
        await coordinator.async_initialize()
        hass.data.setdefault(DOMAIN, {})[entry_id] = coordinator
        return coordinator

    return _make
