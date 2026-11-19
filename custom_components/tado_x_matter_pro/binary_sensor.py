"""Whether a window counts as open (after the open delay), and whether it is open too long."""

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
    """Per room with windows: open, and – with a reminder time – open too long.

    A room that loses its windows or its reminder time loses the sensors.
    """
    registry = er.async_get(hass)
    for room_id, room in entry.runtime_data.rooms.items():
        wanted: dict[str, BinarySensorEntity] = {}
        if room.windows:
            wanted["window_open"] = WindowOpen(room)
            if room.remind_minutes:
                wanted["window_overdue"] = WindowOverdue(room)
        for key in ("window_open", "window_overdue"):
            if key not in wanted and (
                entity_id := registry.async_get_entity_id(
                    "binary_sensor", DOMAIN, f"{room_id}_{key}"
                )
            ):
                registry.async_remove(entity_id)
        async_add_entities(list(wanted.values()), config_subentry_id=room_id)


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


class WindowOverdue(RoomEntity, BinarySensorEntity):
    """On while a window keeps the room off longer than the room's reminder time."""

    _attr_translation_key = "window_overdue"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, room: RoomController) -> None:
        """Create the sensor."""
        super().__init__(room, "window_overdue")

    @property
    def is_on(self) -> bool:
        """Open too long – whether or not it was cold enough outside to remind."""
        desired = self.room.desired
        return desired is not None and desired.window_overdue
