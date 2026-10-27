"""Rooms in Home Assistant: plan, windows, manual changes, the room thermostat and numbers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from tests.python.conftest import FakeTrv, set_inputs

type Setup = Callable[..., Awaitable[MockConfigEntry]]

# The kitchen is in an area (device "Heating"), the bathroom is not (device named after the room).
ROOM_IDS = {"kitchen": "kitchen_heating", "bathroom": "bathroom"}


def trv_state(hass: HomeAssistant, entity_id: str) -> tuple[str, float | None]:
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state, state.attributes.get("temperature")


def mode(hass: HomeAssistant, room: str) -> str:
    state = hass.states.get(f"sensor.{ROOM_IDS[room]}_mode")
    assert state is not None
    return state.state


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_rooms_follow_their_schedule(hass: HomeAssistant, setup_house: Setup) -> None:
    await setup_house()
    assert trv_state(hass, "climate.kitchen_trv") == ("heat", 21.0)
    assert trv_state(hass, "climate.bath_trv") == ("heat", 18.0)
    assert mode(hass, "kitchen") == "schedule"
    assert mode(hass, "bathroom") == "idle"
    room = hass.states.get("climate.kitchen_heating")
    assert room is not None
    assert room.state == "auto"
    assert room.attributes["temperature"] == 21.0

    set_inputs(hass, bathroom="on")
    await hass.async_block_till_done()
    assert trv_state(hass, "climate.bath_trv") == ("heat", 21.0)
    assert trv_state(hass, "climate.bath_tub_trv") == ("heat", 21.0)


async def test_block_temperature_and_away(hass: HomeAssistant, setup_house: Setup) -> None:
    await setup_house()
    hass.states.async_set("schedule.ground_floor", "on", {"temperature": 22.5})
    await hass.async_block_till_done()
    assert trv_state(hass, "climate.kitchen_trv") == ("heat", 22.5)

    set_inputs(hass, away="on")
    await hass.async_block_till_done()
    assert trv_state(hass, "climate.kitchen_trv") == ("heat", 18.0)
    assert mode(hass, "kitchen") == "idle"


async def test_window_switches_off_after_the_delay_and_back_on(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    set_inputs(hass, kitchen_window="on")
    await hass.async_block_till_done()
    assert trv_state(hass, "climate.kitchen_trv")[0] == "heat"

    await advance(hass, freezer, 30)
    assert trv_state(hass, "climate.kitchen_trv")[0] == "off"
    assert mode(hass, "kitchen") == "window"
    window = hass.states.get("binary_sensor.kitchen_heating_window_open")
    assert window is not None
    assert window.state == "on"

    back_on = hass.states.get("sensor.kitchen_heating_back_on")
    assert back_on is not None
    assert back_on.state == "unknown"  # no countdown while the window is still open

    set_inputs(hass, kitchen_window="off")
    await hass.async_block_till_done()
    assert mode(hass, "kitchen") == "waiting"
    back_on = hass.states.get("sensor.kitchen_heating_back_on")
    assert back_on is not None
    resumes = dt_util.parse_datetime(back_on.state)
    assert resumes is not None
    assert abs(resumes - (dt_util.utcnow() + timedelta(minutes=5))) < timedelta(seconds=1)
    await advance(hass, freezer, 5 * 60)
    assert trv_state(hass, "climate.kitchen_trv") == ("heat", 21.0)
    assert mode(hass, "kitchen") == "schedule"
    back_on = hass.states.get("sensor.kitchen_heating_back_on")
    assert back_on is not None
    assert back_on.state == "unknown"


async def test_a_door_opened_for_seconds_changes_nothing(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    writes = len(trvs["climate.kitchen_trv"].writes)
    set_inputs(hass, kitchen_window="on")
    await hass.async_block_till_done()
    await advance(hass, freezer, 5)
    set_inputs(hass, kitchen_window="off")
    await hass.async_block_till_done()
    await advance(hass, freezer, 60)
    assert len(trvs["climate.kitchen_trv"].writes) == writes
    assert mode(hass, "kitchen") == "schedule"


async def test_dial_turn_holds_syncs_siblings_until_the_next_change(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    set_inputs(hass, bathroom="on")
    await hass.async_block_till_done()

    trvs["climate.bath_trv"].dial(23.0)
    await hass.async_block_till_done()
    await advance(hass, freezer, 4)
    assert mode(hass, "bathroom") == "manual"
    assert trv_state(hass, "climate.bath_tub_trv") == ("heat", 23.0)
    assert trv_state(hass, "climate.bath_trv") == ("heat", 23.0)

    set_inputs(hass, bathroom="off")
    await hass.async_block_till_done()
    assert mode(hass, "bathroom") == "idle"
    assert trv_state(hass, "climate.bath_trv") == ("heat", 18.0)


async def test_our_own_writes_are_not_manual_changes(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    set_inputs(hass, bathroom="on")
    await hass.async_block_till_done()
    await advance(hass, freezer, 10)
    assert mode(hass, "bathroom") == "schedule"
    assert mode(hass, "kitchen") == "schedule"


async def test_room_thermostat_modes(hass: HomeAssistant, setup_house: Setup) -> None:
    await setup_house()
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.kitchen_heating", "temperature": 23.5},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert trv_state(hass, "climate.kitchen_trv") == ("heat", 23.5)
    room = hass.states.get("climate.kitchen_heating")
    assert room is not None
    assert room.state == "heat"

    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.kitchen_heating", "hvac_mode": "off"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert trv_state(hass, "climate.kitchen_trv")[0] == "off"
    assert mode(hass, "kitchen") == "off"
    set_inputs(hass, ground_floor="off")  # room off survives plan changes
    await hass.async_block_till_done()
    assert mode(hass, "kitchen") == "off"

    await hass.services.async_call(
        "climate", "turn_on", {"entity_id": "climate.kitchen_heating"}, blocking=True
    )
    await hass.async_block_till_done()
    assert trv_state(hass, "climate.kitchen_trv") == ("heat", 18.0)
    assert mode(hass, "kitchen") == "idle"


async def test_numbers_change_the_plan(hass: HomeAssistant, setup_house: Setup) -> None:
    await setup_house()
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.kitchen_heating_comfort_temperature", "value": 22},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert trv_state(hass, "climate.kitchen_trv") == ("heat", 22.0)
    number = hass.states.get("number.kitchen_heating_comfort_temperature")
    assert number is not None
    assert number.state == "22.0"


async def test_reload_writes_nothing(
    hass: HomeAssistant, setup_house: Setup, trvs: dict[str, FakeTrv]
) -> None:
    entry = await setup_house()
    writes = {eid: len(trv.writes) for eid, trv in trvs.items()}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert {eid: len(trv.writes) for eid, trv in trvs.items()} == writes
    assert mode(hass, "kitchen") == "schedule"


async def test_change_while_stopped_becomes_a_hold(
    hass: HomeAssistant, setup_house: Setup, trvs: dict[str, FakeTrv]
) -> None:
    entry = await setup_house()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    trvs["climate.kitchen_trv"].dial(19.5)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert mode(hass, "kitchen") == "manual"
    assert trv_state(hass, "climate.kitchen_trv") == ("heat", 19.5)


async def test_entities_belong_to_the_room_device(hass: HomeAssistant, setup_house: Setup) -> None:
    entry = await setup_house()
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    by_room: dict[str | None, set[str]] = {}
    for entity in entities:
        by_room.setdefault(entity.config_subentry_id, set()).add(entity.entity_id)
    assert len(by_room) == 2
    kitchen = next(ids for ids in by_room.values() if "climate.kitchen_heating" in ids)
    assert kitchen == {
        "climate.kitchen_heating",
        "sensor.kitchen_heating_mode",
        "number.kitchen_heating_comfort_temperature",
        "number.kitchen_heating_eco_temperature",
        "binary_sensor.kitchen_heating_window_open",
        "sensor.kitchen_heating_back_on",
        "sensor.kitchen_heating_kitchen_trv_heating",
    }
    climate = registry.async_get("climate.kitchen_heating")
    assert climate is not None
    assert {registry.async_get(e).device_id for e in kitchen} == {climate.device_id}  # type: ignore[union-attr]
