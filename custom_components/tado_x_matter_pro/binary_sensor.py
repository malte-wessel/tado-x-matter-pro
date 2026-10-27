"""Whether a window counts as open: after the open delay, so short openings are ignored."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .const import DOMAIN
from .controller import RoomController
from .engine.model import WindowPhase
from .entity import RoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One window sensor per room with windows; a room without windows loses its sensor."""
    registry = er.async_get(hass)
    for room_id, room in entry.runtime_data.rooms.items():
        if room.windows:
            async_add_entities([WindowOpen(room)], config_subentry_id=room_id)
        elif entity_id := registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{room_id}_window_open"
        ):
            registry.async_remove(entity_id)


class WindowOpen(RoomEntity, BinarySensorEntity):
    """On while a window is open long enough to count."""

    _attr_translation_key = "window_open"
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, room: RoomController) -> None:
        """Create the window sensor."""
        super().__init__(room, "window_open")

    @property
    def is_on(self) -> bool:
        """Open after the open delay."""
        return self.room.state.window is WindowPhase.OPEN
