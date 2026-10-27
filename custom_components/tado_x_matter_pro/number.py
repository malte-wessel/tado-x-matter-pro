"""The room's heating and idle temperatures."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .const import MAX_TEMPERATURE, MIN_TEMPERATURE
from .controller import RoomController
from .engine.model import TEMPERATURE_STEP
from .entity import RoomEntity

# entity key → the room's stored temperature (comfort = during blocks, eco = outside and away)
KEYS = {"comfort_temperature": "heating_temperature", "eco_temperature": "idle_temperature"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Comfort and eco temperature per room."""
    for room_id, room in entry.runtime_data.rooms.items():
        async_add_entities([RoomTemperature(room, key) for key in KEYS], config_subentry_id=room_id)


class RoomTemperature(RoomEntity, NumberEntity):
    """A temperature the plan uses; stored with the room."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = MIN_TEMPERATURE
    _attr_native_max_value = MAX_TEMPERATURE
    _attr_native_step = TEMPERATURE_STEP
    _attr_mode = NumberMode.SLIDER

    def __init__(self, room: RoomController, key: str) -> None:
        """Create the number for `key`."""
        super().__init__(room, key)
        self._key = KEYS[key]
        self._attr_translation_key = key

    @property
    def native_value(self) -> float:
        """The stored temperature."""
        if self._key == "heating_temperature":
            return self.room.heating_temperature
        return self.room.idle_temperature

    async def async_set_native_value(self, value: float) -> None:
        """Store it and apply the plan at once."""
        self.room.set_number(self._key, value)
