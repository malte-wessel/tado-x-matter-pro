"""Window and door contacts, switched with the `dev_house.set_window` service."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DevHouseConfigEntry
from .entity import DevHouseEntity, device
from .house import ROOMS
from .sim import Simulation


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DevHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One contact per window or door."""
    async_add_entities(
        Contact(entry.runtime_data, room.name, window.object_id, window.name, door=window.door)
        for room in ROOMS
        for window in room.windows
    )


class Contact(DevHouseEntity, BinarySensorEntity):
    """A window or door contact."""

    def __init__(
        self, sim: Simulation, room: str, object_id: str, name: str, *, door: bool
    ) -> None:
        """Create the contact."""
        dev = device(object_id, name, "Door and Window Sensor", "Dev House", room)
        super().__init__(sim, f"binary_sensor.{object_id}", dev, None)
        self.object_id = object_id
        self._attr_device_class = (
            BinarySensorDeviceClass.DOOR if door else BinarySensorDeviceClass.WINDOW
        )

    @property
    def is_on(self) -> bool:
        """Open."""
        return self.sim.room_of_window(self.object_id).windows[self.object_id]
