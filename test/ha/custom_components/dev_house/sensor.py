"""Thermostat temperature and humidity, room sensors and the outdoor temperature."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DevHouseConfigEntry
from .entity import DevHouseEntity, device, trv_device
from .house import ROOMS
from .sim import Simulation


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DevHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Per thermostat temperature + humidity, per room sensor, one outdoor sensor."""
    sim = entry.runtime_data
    entities: list[SensorEntity] = []
    for room in ROOMS:
        state = sim.rooms[room.name]
        for trv in room.trvs:
            dev = trv_device(trv.object_id, trv.name, room.name)
            entities.append(
                Temperature(
                    sim,
                    f"sensor.{trv.object_id}_temperature",
                    dev,
                    lambda oid=trv.object_id: round(sim.trv_reading(oid), 2),
                )
            )
            entities.append(
                Humidity(
                    sim,
                    f"sensor.{trv.object_id}_humidity",
                    dev,
                    lambda s=state: s.humidity,
                )
            )
        if room.room_sensor:
            dev = device(
                room.room_sensor,
                f"Presence Sensor {room.name}",
                "Presence Sensor",
                "Dev House",
                room.name,
            )
            entities.append(
                Temperature(sim, f"sensor.{room.room_sensor}", dev, lambda s=state: round(s.air, 1))
            )
    outdoor = device("weather_station", "Weather Station", "Weather Station", "Dev House", "Garden")
    entities.append(
        Temperature(sim, "sensor.outdoor_temperature", outdoor, lambda: round(sim.outdoor, 1))
    )
    async_add_entities(entities)


class Temperature(DevHouseEntity, SensorEntity):
    """A temperature reading of the simulation."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, sim: Simulation, entity_id: str, dev: DeviceInfo, value: Callable[[], float]
    ) -> None:
        """Read `value` on every write."""
        super().__init__(sim, entity_id, dev, "Temperature")
        self._value = value

    @property
    def native_value(self) -> float:
        """The current reading."""
        return self._value()


class Humidity(Temperature):
    """Relative humidity of the room, as the thermostat reports it."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self, sim: Simulation, entity_id: str, dev: DeviceInfo, value: Callable[[], float]
    ) -> None:
        """Same as a temperature, other unit."""
        super().__init__(sim, entity_id, dev, value)
        self._attr_name = "Humidity"
