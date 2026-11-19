"""The room's mode, when heating resumes after a window, and per thermostat whether it heats."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .const import DOMAIN
from .controller import RoomController
from .engine.heating import Status
from .engine.model import Mode
from .entity import HouseEntity, RoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Per room the mode, when heating resumes, and a status per thermostat with a demand."""
    registry = er.async_get(hass)
    for room_id, room in entry.runtime_data.rooms.items():
        entities: list[SensorEntity] = [ModeSensor(room)]
        if room.windows:
            entities.append(BackOn(room))
        elif entity_id := registry.async_get_entity_id("sensor", DOMAIN, f"{room_id}_back_on"):
            registry.async_remove(entity_id)  # the room lost its windows
        statuses = [
            ThermostatStatus(
                room,
                thermostat,
                _thermostat_key(hass, thermostat),
                _thermostat_name(hass, thermostat),
            )
            for thermostat in room.thermostats
            if thermostat in room.demand
        ]
        # Status sensors of thermostats that left the room or lost their demand entity go.
        keep = {status.unique_id for status in statuses}
        for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            unique_id = registry_entry.unique_id
            if unique_id.startswith(f"{room_id}_status_") and unique_id not in keep:
                registry.async_remove(registry_entry.entity_id)
        async_add_entities([*entities, *statuses], config_subentry_id=room_id)
    async_add_entities([RoomsOffSchedule(entry, entry.runtime_data.rooms.values())])


def _thermostat_key(hass: HomeAssistant, thermostat: str) -> str:
    """Return the thermostat's registry id, which survives renaming its entity id."""
    registry_entry = er.async_get(hass).async_get(thermostat)
    return registry_entry.id if registry_entry else thermostat


def _thermostat_name(hass: HomeAssistant, thermostat: str) -> str:
    """Return the thermostat's name, also before its integration has set it up."""
    if state := hass.states.get(thermostat):
        return state.name
    registry_entry = er.async_get(hass).async_get(thermostat)
    if registry_entry is None:
        return thermostat
    if registry_entry.name or registry_entry.original_name:
        return str(registry_entry.name or registry_entry.original_name)
    device = (
        dr.async_get(hass).async_get(registry_entry.device_id) if registry_entry.device_id else None
    )
    return (device.name_by_user or device.name or thermostat) if device else thermostat


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
    """Whether one thermostat is heating, has reached its setpoint, or is off (from its demand)."""

    _attr_translation_key = "thermostat_status"
    _attr_device_class = SensorDeviceClass.ENUM
    # The demand entity records its own history; a copy here would add a row with every change.
    _unrecorded_attributes = frozenset({"demand"})

    def __init__(self, room: RoomController, thermostat: str, key: str, name: str) -> None:
        """Create the status sensor of `thermostat`, named after it."""
        super().__init__(room, f"status_{key}")
        self.thermostat = thermostat
        self._attr_options = [str(status) for status in Status]
        self._attr_translation_placeholders = {"thermostat": name}

    @property
    def native_value(self) -> str | None:
        """Heating, reached or off; unknown while the thermostat or its demand is unavailable."""
        status = self.room.status(self.thermostat)
        return str(status) if status is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The thermostat and its demand (a number, on/off, or None)."""
        return {
            "thermostat": self.thermostat,
            "demand": self.room.demand_value(self.thermostat),
        }


class RoomsOffSchedule(HouseEntity, SensorEntity):
    """How many rooms "resume all" would change: holds, overrides, rooms switched off."""

    _attr_translation_key = "rooms_off_schedule"
    _attr_native_unit_of_measurement = "rooms"

    def __init__(self, entry: HeatingConfigEntry, rooms: Iterable[RoomController]) -> None:
        """Create the house's count."""
        super().__init__(entry, rooms, "rooms_off_schedule")

    @property
    def available(self) -> bool:
        """Available once the rooms have decided."""
        return all(room.desired is not None for room in self.rooms)

    @property
    def native_value(self) -> int:
        """The number of rooms off their schedule."""
        return sum(room.off_schedule for room in self.rooms)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Those rooms, each with its mode."""
        return {
            "rooms": {
                room.name: str(room.desired.mode)
                for room in self.rooms
                if room.off_schedule and room.desired is not None
            }
        }
