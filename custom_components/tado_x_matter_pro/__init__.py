"""Tado X Matter Pro – room heating control for Tado X thermostats over Matter."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .config_flow import TadoXMatterProConfigFlow
from .const import DOMAIN, SUBENTRY_ROOM
from .controller import RoomController
from .store import HeatingStore

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.NUMBER, Platform.SENSOR]


@dataclass
class HeatingData:
    """What a loaded entry holds: the store and one controller per room."""

    store: HeatingStore
    rooms: dict[str, RoomController]


type HeatingConfigEntry = ConfigEntry[HeatingData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration once per run (entity services follow in phase 4)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    """Set up the house: one controller per room, entities, then start deciding."""
    rooms_config = {
        subentry_id: subentry
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_ROOM
    }
    store = HeatingStore(hass)
    await store.async_load(set(rooms_config))
    rooms = {
        subentry_id: RoomController(hass, entry, subentry, store)
        for subentry_id, subentry in rooms_config.items()
    }
    entry.runtime_data = HeatingData(store, rooms)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _start(_hass: HomeAssistant) -> None:
        # Thermostats, schedules and sensors of other integrations exist once HA has started.
        for room in rooms.values():
            await room.async_start()

    entry.async_on_unload(async_at_started(hass, _start))
    for room in rooms.values():
        entry.async_on_unload(room.async_stop)
    # Options and rooms (subentries) change what exists: reload.
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: HeatingConfigEntry) -> None:
    """Reload on option and room changes."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    """Unload the platforms and save; the controllers stop through async_on_unload."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.store.async_flush()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, _entry: ConfigEntry) -> None:
    """Delete the stored rooms once the integration is removed."""
    await HeatingStore(hass).async_remove()


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring an older config entry up to date; refuse one from a newer version."""
    if entry.version > TadoXMatterProConfigFlow.VERSION:
        _LOGGER.error(
            "Config entry version %s.%s is newer than this version of Tado X Matter Pro supports",
            entry.version,
            entry.minor_version,
        )
        return False
    hass.config_entries.async_update_entry(
        entry,
        version=TadoXMatterProConfigFlow.VERSION,
        minor_version=TadoXMatterProConfigFlow.MINOR_VERSION,
    )
    return True
