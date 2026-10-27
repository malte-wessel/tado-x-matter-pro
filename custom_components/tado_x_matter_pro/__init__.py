"""Tado X Matter Pro – room heating control for Tado X thermostats over Matter."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .config_flow import TadoXMatterProConfigFlow
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration once per run (entity services follow in phase 4)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the house from its config entry."""
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on option and room (subentry) changes."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    return True


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
