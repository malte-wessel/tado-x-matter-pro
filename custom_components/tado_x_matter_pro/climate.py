"""The room thermostat: auto follows the plan, heat holds a temperature, off is off."""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_NONE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HeatingConfigEntry
from .const import DOMAIN, MAX_TEMPERATURE, MIN_TEMPERATURE
from .controller import RoomController
from .engine.heating import Status
from .engine.model import TEMPERATURE_STEP
from .entity import RoomEntity
from .services import next_local


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
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, room: RoomController) -> None:
        """Create the room thermostat."""
        super().__init__(room, "climate")
        self._attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]
        self._attr_preset_modes = [PRESET_NONE, PRESET_BOOST, PRESET_COMFORT, PRESET_ECO]

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Auto while the plan decides; heat for anything else someone set; off when switched off.

        Heat covers holds, timed overrides, extended blocks and boost: picking auto ends them.
        Also while a window or frost protection overrides it, it stays the room's mode.
        """
        if self.room.desired is None:
            return None
        override = self.room.state.override
        if override is not None and override.temperature is None:
            return HVACMode.OFF
        if override is not None or self.room.state.boost is not None:
            return HVACMode.HEAT
        return HVACMode.AUTO

    @property
    def hvac_action(self) -> HVACAction | None:
        """Off, heating while any thermostat heats, idle once all with a demand have reached.

        Without demand entities only "off" is known.
        """
        action = self.room.action
        if action is None:
            return None
        return {
            Status.HEATING: HVACAction.HEATING,
            Status.REACHED: HVACAction.IDLE,
            Status.OFF: HVACAction.OFF,
        }[action]

    @property
    def target_temperature(self) -> float | None:
        """The setpoint; while a window pauses the room, the one it returns to; empty when off."""
        desired = self.room.desired
        if desired is None:
            return None
        if desired.temperature is not None:
            return desired.temperature  # heating: the plan, a hold, or frost protection
        override = self.room.state.override
        if override is not None:
            return override.temperature  # a hold it returns to; a room switched off stays empty
        return desired.plan_target

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

    async def async_resume_schedule(self) -> None:
        """Back to the schedule; returns at once, the thermostats are written in the background."""
        self.room.resume()

    @property
    def preset_mode(self) -> str:
        """Boost while it runs; comfort or eco while a preset holds; else none."""
        return self.room.preset

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Boost as the house settings say; comfort or eco until the next plan change; none ends."""
        if preset_mode == PRESET_BOOST:
            self.room.boost()
        elif preset_mode == PRESET_COMFORT:
            self.room.set_override(self.room.heating_temperature, preset=PRESET_COMFORT)
        elif preset_mode == PRESET_ECO:
            self.room.set_override(self.room.idle_temperature, preset=PRESET_ECO)
        else:
            self.room.end_preset()

    async def async_boost(
        self, duration: timedelta | None = None, temperature: float | None = None
    ) -> None:
        """Boost; without fields as the house settings say."""
        self.room.boost(temperature, duration)

    async def async_set_override(
        self,
        temperature: float | None = None,
        preset: str | None = None,
        until: time | None = None,
        duration: timedelta | None = None,
        until_next_change: bool = False,  # noqa: FBT001, FBT002, ARG002 – the default anyway
    ) -> None:
        """Heat at a temperature (or comfort/eco) until a time, for a while, or the next change."""
        if (temperature is None) == (preset is None):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="temperature_or_preset"
            )
        if temperature is None:
            temperature = (
                self.room.heating_temperature
                if preset == PRESET_COMFORT
                else self.room.idle_temperature
            )
        end = next_local(until) if until else (dt_util.utcnow() + duration if duration else None)
        self.room.set_override(temperature, end)

    async def async_extend_block(self, until: time) -> None:
        """Keep the plan's current temperature until a time (today, or tomorrow if past)."""
        self.room.extend_block(next_local(until))
