"""The room thermostat: auto follows the plan, heat holds a temperature, off is off."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .const import MAX_TEMPERATURE, MIN_TEMPERATURE
from .controller import RoomController
from .engine.inference import Status
from .engine.model import TEMPERATURE_STEP, Mode
from .entity import RoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeatingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One room thermostat per room."""
    for room_id, room in entry.runtime_data.rooms.items():
        async_add_entities([RoomThermostat(room)], config_subentry_id=room_id)


class RoomThermostat(RoomEntity, ClimateEntity):
    """The room as one thermostat."""

    _attr_name = None
    _attr_translation_key = "room"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = TEMPERATURE_STEP
    _attr_min_temp = MIN_TEMPERATURE
    _attr_max_temp = MAX_TEMPERATURE
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, room: RoomController) -> None:
        """Create the room thermostat."""
        super().__init__(room, "climate")
        self._attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Off when the room is switched off, heat during a manual hold, else auto."""
        if self.room.desired is None:
            return None
        override = self.room.state.override
        if override is None or isinstance(override.expires, datetime):
            return HVACMode.AUTO  # the plan, or (later) a timed override
        # also while a window or frost protection overrides the hold, it is still the room's mode
        return HVACMode.OFF if override.temperature is None else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Heating while any thermostat heats (inferred), idle once all reached, else off."""
        return {
            Status.HEATING: HVACAction.HEATING,
            Status.REACHED: HVACAction.IDLE,
            Status.OFF: HVACAction.OFF,
        }[self.room.monitor.room_status]

    @property
    def target_temperature(self) -> float | None:
        """The setpoint; while a window pauses the room, the one it returns to."""
        desired = self.room.desired
        if desired is None or desired.mode is Mode.OFF:
            return None
        return desired.temperature if desired.temperature is not None else desired.plan_target

    @property
    def current_temperature(self) -> float | None:
        """The room sensor, or the thermostats' mean."""
        inputs = self.room.inputs
        return inputs.room_temperature if inputs else None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Hold a temperature until the next plan change."""
        if kwargs.get(ATTR_HVAC_MODE) == HVACMode.OFF:
            self.room.set_mode("off")
            return
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self.room.set_temperature(float(temperature))
        elif (mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            self.room.set_mode(str(mode))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Auto, heat or off."""
        self.room.set_mode(str(hvac_mode))

    async def async_turn_on(self) -> None:
        """Back to the plan."""
        self.room.set_mode("auto")

    async def async_turn_off(self) -> None:
        """Switch the room off."""
        self.room.set_mode("off")
