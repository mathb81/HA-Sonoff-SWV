from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    LEGACY_STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

# hass.data key of the lock that serialises the one-off migration of the
# legacy shared file, so that two valves set up at the same time cannot
# both adopt it.
_MIGRATION_LOCK = f"{DOMAIN}_storage_migration_lock"


def storage_key(entry_id: str) -> str:
    """Return the storage key of one config entry (one valve)."""

    return f"{DOMAIN}.{entry_id}"


def _normalize_ieee(ieee: str | None) -> str:
    return str(ieee or "").lower().replace("0x", "")


async def async_remove_storage(
    hass: HomeAssistant,
    entry_id: str,
) -> None:
    """Delete the stored data of a config entry that has been removed."""

    await Store(
        hass,
        STORAGE_VERSION,
        storage_key(entry_id),
    ).async_remove()


class SonoffStorage:
    """Persistent storage for one Sonoff SWV valve.

    Each config entry has its own file (.storage/sonoff_swv.<entry_id>).
    Versions before multi-valve support kept everything in a single file
    (.storage/sonoff_swv) shared by all entries, so with several valves
    each one overwrote the plans, history and settings of the others.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        ieee: str | None = None,
    ) -> None:

        self._hass = hass

        self._ieee = ieee

        self._store = Store(
            hass,
            STORAGE_VERSION,
            storage_key(entry_id),
        )

    async def load(
        self,
    ) -> dict[str, Any]:
        """Load stored data."""

        data = await self._store.async_load()

        if data is None:
            data = await self._async_migrate_legacy()

        if data is None:

            return {
                "device": {},
            }

        return data

    async def save(
        self,
        data: dict[str, Any],
    ) -> None:
        """Save stored data."""

        await self._store.async_save(
            data
        )

    async def _async_migrate_legacy(
        self,
    ) -> dict[str, Any] | None:
        """Adopt the legacy shared file if it belongs to this valve.

        The file is moved to the first valve that matches it and then
        deleted, so it is adopted at most once.
        """

        lock = self._hass.data.setdefault(
            _MIGRATION_LOCK,
            asyncio.Lock(),
        )

        async with lock:

            legacy = Store(
                self._hass,
                STORAGE_VERSION,
                LEGACY_STORAGE_KEY,
            )

            data = await legacy.async_load()

            if not isinstance(data, dict) or not self._legacy_belongs_here(data):
                return None

            await self._store.async_save(data)

            await legacy.async_remove()

            _LOGGER.info(
                "Migrated legacy shared storage to the per-valve storage "
                "of %s",
                self._ieee or "the only configured valve",
            )

            return data

    def _legacy_belongs_here(
        self,
        data: dict[str, Any],
    ) -> bool:
        """Tell whether the legacy shared file describes this valve."""

        device = data.get("device")

        legacy_ieee = (
            device.get("ieee")
            if isinstance(device, dict)
            else None
        )

        if legacy_ieee and self._ieee:
            return _normalize_ieee(legacy_ieee) == _normalize_ieee(self._ieee)

        # No IEEE to compare: only safe when there is a single valve.
        return len(self._hass.config_entries.async_entries(DOMAIN)) == 1
