"""Buttons: back to the schedule, per room and for all rooms at once."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .controller import RoomController
from .entity import HouseEntity, RoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a resume button per room, and one for the whole house."""
    rooms = entry.runtime_data.rooms
    for room_id, room in rooms.items():
        async_add_entities([ResumeRoom(room)], config_subentry_id=room_id)
    async_add_entities([ResumeAll(entry, rooms.values())])


class ResumeRoom(RoomEntity, ButtonEntity):
    """Back to the schedule: ends holds, overrides, room off and the wait after a window."""

    _attr_translation_key = "resume"

    def __init__(self, room: RoomController) -> None:
        """Create the room's resume button."""
        super().__init__(room, "resume")

    async def async_press(self) -> None:
        """Resume; the thermostats are written in the background."""
        self.room.resume()


class ResumeAll(HouseEntity, ButtonEntity):
    """Every room back to its schedule."""

    _attr_translation_key = "resume_all"

    def __init__(self, entry: HeatingConfigEntry, rooms: Iterable[RoomController]) -> None:
        """Create the house's resume button."""
        super().__init__(entry, rooms, "resume_all")

    @property
    def available(self) -> bool:
        """Available once the rooms have decided."""
        return all(room.desired is not None for room in self.rooms)

    async def async_press(self) -> None:
        """Resume every room; none waits for another."""
        for room in self.rooms:
            room.resume()
