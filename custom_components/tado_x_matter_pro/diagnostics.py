"""Diagnostics: the house settings and per room its state, decisions, writes and trace."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import HeatingConfigEntry
from .const import CONF_NOTIFY, DOMAIN

# Notify targets are usually named after people's phones.
TO_REDACT = {CONF_NOTIFY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: HeatingConfigEntry,
) -> dict[str, Any]:
    """Return the house settings and every room."""
    return {
        "house": async_redact_data(dict(entry.options), TO_REDACT),
        "rooms": {
            room_id: room.diagnostics() for room_id, room in entry.runtime_data.rooms.items()
        },
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    entry: HeatingConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return one room (its device)."""
    rooms = entry.runtime_data.rooms
    room_id = next((i for d, i in device.identifiers if d == DOMAIN and i in rooms), None)
    return rooms[room_id].diagnostics() if room_id else {}
