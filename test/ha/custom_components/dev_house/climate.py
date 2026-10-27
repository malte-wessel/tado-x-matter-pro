"""Tado X-like thermostats: `off`/`heat` only, no action; mode and setpoint reported separately."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DevHouseConfigEntry
from .const import CONF_REPORT_DELAY, DOMAIN
from .entity import DevHouseEntity, trv_device
from .house import ROOMS
from .sim import Simulation, TrvState


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DevHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One climate per thermostat."""
    delay = float(entry.data.get(CONF_REPORT_DELAY, 1.5))
    entities = [
        DevHouseThermostat(entry.runtime_data, trv.object_id, trv.name, room.name, delay)
        for room in ROOMS
        for trv in room.trvs
    ]
    hass.data[DOMAIN]["climates"] = {e.object_id: e for e in entities}
    async_add_entities(entities)


class DevHouseThermostat(DevHouseEntity, ClimateEntity):
    """A simulated Tado X thermostat as Home Assistant's Matter integration shows it."""

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_min_temp = 5
    _attr_max_temp = 30
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self, sim: Simulation, object_id: str, name: str, area: str, report_delay: float
    ) -> None:
        """Create the thermostat; the delay is how long a written setpoint takes to come back."""
        super().__init__(sim, f"climate.{object_id}", trv_device(object_id, name, area), None)
        self.object_id = object_id
        self.report_delay = report_delay

    @property
    def _trv(self) -> TrvState:
        return self.sim.room_of_trv(self.object_id).trvs[self.object_id]

    @property
    def available(self) -> bool:
        """Unavailable while the simulated connection is down."""
        return self._trv.available

    @property
    def hvac_mode(self) -> HVACMode:
        """Off or heat."""
        return HVACMode(self._trv.hvac_mode)

    @property
    def target_temperature(self) -> float:
        """The setpoint (kept while off, as on the real device)."""
        return self._trv.setpoint

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The simulation's truth, to check the inferred status against."""
        return {"valve_open": self._trv.valve_open}

    @property
    def current_temperature(self) -> float:
        """The thermostat's own reading, at 0.1 °C like the Matter climate."""
        return round(self.sim.trv_reading(self.object_id), 1)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Mode first, then the setpoint after the report delay (Matter writes both separately)."""
        mode = kwargs.get(ATTR_HVAC_MODE)
        if mode is not None and mode != self._trv.hvac_mode:
            self._trv.hvac_mode = str(mode)
            self.async_write_ha_state()
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None or float(temperature) == self._trv.setpoint:
            return
        await asyncio.sleep(self.report_delay)
        self._trv.setpoint = float(temperature)
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Switch between off and heat after the report delay."""
        await asyncio.sleep(self.report_delay)
        self._trv.hvac_mode = str(hvac_mode)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Heat."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_dial(self, temperature: float | None, hvac_mode: str | None) -> None:
        """Someone turned the dial: half-degree steps, each reported without a HA context."""
        if hvac_mode is not None:
            self._trv.hvac_mode = hvac_mode
            self.async_set_context(Context())
            self.async_write_ha_state()
        if temperature is None:
            return
        step = 0.5 if temperature > self._trv.setpoint else -0.5
        while abs(temperature - self._trv.setpoint) >= 0.5:
            await asyncio.sleep(0.4)
            self._trv.setpoint = round(self._trv.setpoint + step, 1)
            self.async_set_context(Context())
            self.async_write_ha_state()
