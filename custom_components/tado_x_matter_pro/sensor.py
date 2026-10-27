"""The room's mode, when heating resumes after a window, and per thermostat whether it heats."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .const import DOMAIN
from .controller import RoomController
from .engine.inference import Status
from .engine.model import Mode
from .entity import RoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Per room the mode and – with windows – when heating resumes; a status per thermostat."""
    registry = er.async_get(hass)
    for room_id, room in entry.runtime_data.rooms.items():
        entities: list[SensorEntity] = [ModeSensor(room)]
        if room.windows:
            entities.append(BackOn(room))
        elif entity_id := registry.async_get_entity_id("sensor", DOMAIN, f"{room_id}_back_on"):
            registry.async_remove(entity_id)  # the room lost its windows
        for thermostat in room.thermostats:
            registry_entry = registry.async_get(thermostat)
            state = hass.states.get(thermostat)
            entities.append(
                ThermostatStatus(
                    room,
                    thermostat,
                    # the registry id survives renaming the thermostat's entity id
                    registry_entry.id if registry_entry else thermostat,
                    state.name if state else thermostat,
                )
            )
        async_add_entities(entities, config_subentry_id=room_id)


class ModeSensor(RoomEntity, SensorEntity):
    """Schedule, idle, manual, window, waiting, off or frost – with the times that matter."""

    _attr_translation_key = "mode"
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, room: RoomController) -> None:
        """Create the mode sensor."""
        super().__init__(room, "mode")
        self._attr_options = [str(mode) for mode in Mode]

    @property
    def native_value(self) -> str | None:
        """The current mode."""
        desired = self.room.desired
        return str(desired.mode) if desired else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Target, plan target and the moments things change."""
        desired = self.room.desired
        if desired is None:
            return {}
        inputs = self.room.inputs
        next_change = self.room.next_change
        next_target = None
        if inputs is not None and next_change is not None:
            next_target = (
                inputs.idle_temperature
                if inputs.schedule_on or inputs.idle
                else inputs.heating_temperature
            )
        return {
            "target": desired.temperature,
            "plan_target": desired.plan_target,
            "next_change": next_change.isoformat() if next_change else None,
            "next_target": next_target,
            "resume_at": desired.resume_at.isoformat() if desired.resume_at else None,
            "override_until": desired.override_until.isoformat()
            if desired.override_until
            else None,
            "window": str(self.room.state.window),
        }


class BackOn(RoomEntity, SensorEntity):
    """When heating resumes after the room's windows were closed; empty otherwise.

    A timestamp, so cards show it as relative time ("in 4 minutes").
    """

    _attr_translation_key = "back_on"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, room: RoomController) -> None:
        """Create the sensor."""
        super().__init__(room, "back_on")

    @property
    def native_value(self) -> datetime | None:
        """The end of the wait after closing, while it runs."""
        desired = self.room.desired
        return desired.resume_at if desired else None


class ThermostatStatus(RoomEntity, SensorEntity):
    """Whether one thermostat is heating, has reached its setpoint, or is off (inferred)."""

    _attr_translation_key = "thermostat_status"
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, room: RoomController, thermostat: str, key: str, name: str) -> None:
        """Create the status sensor of `thermostat`, named after it."""
        super().__init__(room, f"status_{key}")
        self.thermostat = thermostat
        self._attr_options = [str(status) for status in Status]
        self._attr_translation_placeholders = {"thermostat": name}

    @property
    def native_value(self) -> str:
        """Heating, reached or off."""
        return str(self.room.monitor.status(self.thermostat))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The thermostat, its reading and the reading's trend (°C/h)."""
        monitor = self.room.monitor
        return {
            "thermostat": self.thermostat,
            "temperature": monitor.reading(self.thermostat),
            "trend": monitor.trend(self.thermostat),
        }
