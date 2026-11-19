"""The heating status per thermostat and the room's action, taken from demand entities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from tests.python.conftest import (
    BATHROOM,
    HOUSE_OPTIONS,
    KITCHEN,
    KITCHEN_DEMAND,
    FakeTrv,
    house_entry,
    set_inputs,
)

type Setup = Callable[..., Awaitable[MockConfigEntry]]
KITCHEN_STATUS = "sensor.kitchen_heating_kitchen_trv_heating"
BATH_STATUS = "sensor.bathroom_bath_trv_heating"
TUB_STATUS = "sensor.bathroom_bath_tub_trv_heating"
BATH_DEMAND = {"climate.bath_trv": "binary_sensor.bath_pipe_hot"}
BOTH_DEMANDS = {**BATH_DEMAND, "climate.bath_tub_trv": "binary_sensor.tub_pipe_hot"}


def state_of(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


def action(hass: HomeAssistant, room: str) -> str | None:
    state = hass.states.get(f"climate.{room}")
    assert state is not None
    return state.attributes.get("hvac_action")


def demand(hass: HomeAssistant, entity_id: str, value: str) -> None:
    unit = {"unit_of_measurement": "%"} if entity_id.startswith("sensor.") else {}
    hass.states.async_set(entity_id, value, unit)


async def setup_with(
    hass: HomeAssistant,
    setup_house: Setup,
    rooms: dict[str, dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    return await setup_house(house_entry(rooms, options))


async def test_a_percentage_heats_from_the_threshold_on(
    hass: HomeAssistant, setup_house: Setup
) -> None:
    demand(hass, "sensor.kitchen_demand", "2.9")
    await setup_with(hass, setup_house, {"Kitchen": {**KITCHEN, "demand": KITCHEN_DEMAND}})
    assert state_of(hass, KITCHEN_STATUS) == "reached"
    assert action(hass, "kitchen_heating") == "idle"
    status = hass.states.get(KITCHEN_STATUS)
    assert status is not None
    assert status.attributes["demand"] == 2.9
    assert status.attributes["thermostat"] == "climate.kitchen_trv"

    demand(hass, "sensor.kitchen_demand", "3")
    await hass.async_block_till_done()
    assert state_of(hass, KITCHEN_STATUS) == "heating"
    assert action(hass, "kitchen_heating") == "heating"


async def test_the_threshold_is_a_house_setting(hass: HomeAssistant, setup_house: Setup) -> None:
    demand(hass, "sensor.kitchen_demand", "40")
    await setup_with(
        hass,
        setup_house,
        {"Kitchen": {**KITCHEN, "demand": KITCHEN_DEMAND}},
        {**HOUSE_OPTIONS, "demand_threshold": 50},
    )
    assert state_of(hass, KITCHEN_STATUS) == "reached"


async def test_an_on_off_demand_and_the_most_active_thermostat(
    hass: HomeAssistant, setup_house: Setup
) -> None:
    demand(hass, "binary_sensor.bath_pipe_hot", "off")
    demand(hass, "binary_sensor.tub_pipe_hot", "off")
    await setup_with(hass, setup_house, {"Bathroom": {**BATHROOM, "demand": BOTH_DEMANDS}})
    assert (state_of(hass, BATH_STATUS), state_of(hass, TUB_STATUS)) == ("reached", "reached")
    assert action(hass, "bathroom") == "idle"

    demand(hass, "binary_sensor.tub_pipe_hot", "on")
    await hass.async_block_till_done()
    assert (state_of(hass, BATH_STATUS), state_of(hass, TUB_STATUS)) == ("reached", "heating")
    assert action(hass, "bathroom") == "heating"


async def test_unknown_while_the_demand_is_unavailable(
    hass: HomeAssistant, setup_house: Setup
) -> None:
    demand(hass, "sensor.kitchen_demand", "20")
    await setup_with(hass, setup_house, {"Kitchen": {**KITCHEN, "demand": KITCHEN_DEMAND}})
    hass.states.async_set("sensor.kitchen_demand", "unavailable")
    await hass.async_block_till_done()
    assert state_of(hass, KITCHEN_STATUS) == "unknown"
    assert action(hass, "kitchen_heating") is None


async def test_unknown_while_the_thermostat_is_unavailable(
    hass: HomeAssistant, setup_house: Setup, trvs: dict[str, FakeTrv]
) -> None:
    demand(hass, "sensor.kitchen_demand", "20")
    await setup_with(hass, setup_house, {"Kitchen": {**KITCHEN, "demand": KITCHEN_DEMAND}})
    trv = trvs["climate.kitchen_trv"]
    trv._attr_available = False
    trv.async_write_ha_state()
    await hass.async_block_till_done()
    assert state_of(hass, KITCHEN_STATUS) == "unknown"


async def test_a_thermostat_that_is_off_is_off_whatever_its_demand(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    demand(hass, "sensor.kitchen_demand", "60")  # a cloud value can lag behind
    await setup_with(hass, setup_house, {"Kitchen": {**KITCHEN, "demand": KITCHEN_DEMAND}})
    set_inputs(hass, kitchen_window="on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert state_of(hass, KITCHEN_STATUS) == "off"
    assert action(hass, "kitchen_heating") == "off"


async def test_without_demand_entities_only_off_is_known(
    hass: HomeAssistant, setup_house: Setup
) -> None:
    await setup_with(hass, setup_house, {"Bathroom": BATHROOM})
    assert hass.states.get(BATH_STATUS) is None
    assert hass.states.get(TUB_STATUS) is None
    assert action(hass, "bathroom") is None

    await hass.services.async_call(
        "climate", "turn_off", {"entity_id": "climate.bathroom"}, blocking=True
    )
    await hass.async_block_till_done()
    assert action(hass, "bathroom") == "off"


async def test_a_room_with_some_demand_entities(hass: HomeAssistant, setup_house: Setup) -> None:
    demand(hass, "binary_sensor.bath_pipe_hot", "off")
    await setup_with(hass, setup_house, {"Bathroom": {**BATHROOM, "demand": BATH_DEMAND}})
    assert state_of(hass, BATH_STATUS) == "reached"
    assert hass.states.get(TUB_STATUS) is None
    assert action(hass, "bathroom") is None  # the tub's thermostat might heat

    demand(hass, "binary_sensor.bath_pipe_hot", "on")
    await hass.async_block_till_done()
    assert action(hass, "bathroom") == "heating"


async def test_a_thermostat_leaving_the_room_takes_its_status_sensor_along(
    hass: HomeAssistant, setup_house: Setup
) -> None:
    demand(hass, "binary_sensor.bath_pipe_hot", "on")
    demand(hass, "binary_sensor.tub_pipe_hot", "on")
    entry = await setup_with(hass, setup_house, {"Bathroom": {**BATHROOM, "demand": BOTH_DEMANDS}})
    assert hass.states.get(TUB_STATUS) is not None
    subentry = next(iter(entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data={**BATHROOM, "thermostats": ["climate.bath_trv"], "demand": BATH_DEMAND},
    )
    await hass.async_block_till_done()
    assert hass.states.get(BATH_STATUS) is not None
    assert hass.states.get(TUB_STATUS) is None
    assert er.async_get(hass).async_get(TUB_STATUS) is None
