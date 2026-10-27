"""Dev House – a simulated house with Tado X-like thermostats, only for the dev Home Assistant.

Configured with `dev_house:` in configuration.yaml (options `speed`, `report_delay`); the entry is
imported from there. Never shipped: the integration under test is tado_x_matter_pro.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    floor_registry as fr,
)
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.typing import ConfigType
import probatio as vol

from .const import CONF_REPORT_DELAY, CONF_SPEED, DOMAIN, TICK
from .house import FLOORS, ROOMS
from .sim import Simulation

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_SPEED, default=1.0): vol.All(
                    vol.Coerce(float), vol.Range(min=0.1, max=360)
                ),
                vol.Optional(CONF_REPORT_DELAY, default=1.5): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=30)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

type DevHouseConfigEntry = ConfigEntry[Simulation]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Import the YAML options as the config entry and register the simulator services."""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=dict(config[DOMAIN])
            )
        )
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DevHouseConfigEntry) -> bool:
    """Create floors and areas, start the simulation, add the devices."""
    _ensure_floors_and_areas(hass)
    sim = Simulation()
    entry.runtime_data = sim
    hass.data[DOMAIN] = {"sim": sim, "options": dict(entry.data), "climates": {}}
    speed = float(entry.data.get(CONF_SPEED, 1.0))

    @callback
    def _tick(_now: datetime) -> None:
        sim.step(TICK.total_seconds() / 3600 * speed)

    entry.async_on_unload(async_track_time_interval(hass, _tick, TICK))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _link_area_sensors(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DevHouseConfigEntry) -> bool:
    """Unload the platforms."""
    hass.data.pop(DOMAIN, None)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _ensure_floors_and_areas(hass: HomeAssistant) -> None:
    floors = fr.async_get(hass)
    areas = ar.async_get(hass)
    for name, level, icon in FLOORS:
        if floors.async_get_floor_by_name(name) is None:
            floors.async_create(name, level=level, icon=icon)
    for room in ROOMS:
        floor = floors.async_get_floor_by_name(room.floor)
        if areas.async_get_area_by_name(room.name) is None and floor is not None:
            areas.async_create(room.name, floor_id=floor.floor_id, icon=room.icon)


def _link_area_sensors(hass: HomeAssistant) -> None:
    """Show each room's temperature and humidity on its area (the entities exist by now)."""
    areas = ar.async_get(hass)
    for room in ROOMS:
        area = areas.async_get_area_by_name(room.name)
        if area is None:
            continue
        first = room.trvs[0].object_id
        areas.async_update(
            area.id,
            temperature_entity_id=f"sensor.{room.room_sensor or first + '_temperature'}",
            humidity_entity_id=f"sensor.{first}_humidity",
        )


def _object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1]


def _sim(hass: HomeAssistant) -> Simulation:
    sim: Simulation = hass.data[DOMAIN]["sim"]
    return sim


def _register_services(hass: HomeAssistant) -> None:
    async def set_window(call: ServiceCall) -> None:
        sim = _sim(hass)
        for entity_id in call.data[ATTR_ENTITY_ID]:
            object_id = _object_id(entity_id)
            windows = sim.room_of_window(object_id).windows
            windows[object_id] = call.data.get("open", not windows[object_id])
        sim.notify()

    async def turn_dial(call: ServiceCall) -> None:
        """A change made at the thermostat itself: no Home Assistant context."""
        climates: dict[str, Any] = hass.data[DOMAIN]["climates"]
        for entity_id in call.data[ATTR_ENTITY_ID]:
            await climates[_object_id(entity_id)].async_dial(
                call.data.get("temperature"), call.data.get("hvac_mode")
            )

    async def set_air_temperature(call: ServiceCall) -> None:
        sim = _sim(hass)
        sim.rooms[call.data["room"]].air = call.data["temperature"]
        sim.notify()

    async def set_outdoor_temperature(call: ServiceCall) -> None:
        sim = _sim(hass)
        sim.outdoor = call.data["temperature"]
        sim.notify()

    async def drop_connection(call: ServiceCall) -> None:
        """Make thermostats unavailable for a while, like a Matter/Thread hiccup."""
        sim = _sim(hass)
        ids = [_object_id(e) for e in call.data[ATTR_ENTITY_ID]]
        for object_id in ids:
            sim.room_of_trv(object_id).trvs[object_id].available = False
        sim.notify()

        @callback
        def _back(_now: datetime) -> None:
            for object_id in ids:
                sim.room_of_trv(object_id).trvs[object_id].available = True
            sim.notify()

        async_call_later(hass, timedelta(seconds=call.data["seconds"]), _back)

    entity_ids = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_ids}, extra=vol.ALLOW_EXTRA)
    hass.services.async_register(
        DOMAIN,
        "set_window",
        set_window,
        vol.All(entity_ids, vol.Schema({vol.Optional("open"): cv.boolean}, extra=vol.ALLOW_EXTRA)),
    )
    hass.services.async_register(
        DOMAIN,
        "turn_dial",
        turn_dial,
        vol.All(
            entity_ids,
            vol.Schema(
                {
                    vol.Optional("temperature"): vol.Coerce(float),
                    vol.Optional("hvac_mode"): vol.In(["off", "heat"]),
                },
                extra=vol.ALLOW_EXTRA,
            ),
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "set_air_temperature",
        set_air_temperature,
        vol.Schema(
            {
                vol.Required("room"): vol.In([r.name for r in ROOMS]),
                vol.Required("temperature"): vol.Coerce(float),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "set_outdoor_temperature",
        set_outdoor_temperature,
        vol.Schema({vol.Required("temperature"): vol.Coerce(float)}),
    )
    hass.services.async_register(
        DOMAIN,
        "drop_connection",
        drop_connection,
        vol.All(
            entity_ids,
            vol.Schema(
                {vol.Optional("seconds", default=12): vol.All(int, vol.Range(min=1, max=3600))},
                extra=vol.ALLOW_EXTRA,
            ),
        ),
    )
