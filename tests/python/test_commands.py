"""Boost, timed overrides, extending a block and the room thermostat's presets."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
import probatio as vol
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.tado_x_matter_pro.const import DOMAIN
from tests.python.conftest import set_inputs

type Setup = Callable[..., Awaitable[MockConfigEntry]]
ROOM = "climate.kitchen_heating"
TRV = "climate.kitchen_trv"
MODE = "sensor.kitchen_heating_mode"


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def setpoint(hass: HomeAssistant) -> tuple[str, float | None]:
    state = hass.states.get(TRV)
    assert state is not None
    return state.state, state.attributes.get("temperature")


def mode(hass: HomeAssistant) -> str:
    state = hass.states.get(MODE)
    assert state is not None
    return state.state


def attribute(hass: HomeAssistant, entity_id: str, name: str) -> Any:
    state = hass.states.get(entity_id)
    assert state is not None
    return state.attributes.get(name)


async def action(hass: HomeAssistant, name: str, **data: Any) -> None:
    await hass.services.async_call(DOMAIN, name, {"entity_id": ROOM, **data}, blocking=True)
    await hass.async_block_till_done()


async def test_boost_with_the_house_settings_then_back(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()  # house boost: 30 °C for 30 minutes
    await action(hass, "boost")
    assert setpoint(hass) == ("heat", 30.0)
    assert mode(hass) == "boost"
    assert attribute(hass, ROOM, "preset_mode") == "boost"
    assert attribute(hass, "sensor.heating_rooms_off_schedule", "rooms") == {"Kitchen": "boost"}
    assert dt_util.parse_datetime(
        attribute(hass, MODE, "boost_until")
    ) == dt_util.utcnow() + timedelta(minutes=30)

    await advance(hass, freezer, 30 * 60)
    assert setpoint(hass) == ("heat", 21.0)
    assert mode(hass) == "schedule"


async def test_boost_with_its_own_temperature_and_duration(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    await action(hass, "boost", temperature=25, duration={"minutes": 10})
    assert setpoint(hass) == ("heat", 25.0)
    await advance(hass, freezer, 10 * 60)
    assert mode(hass) == "schedule"


async def test_an_override_for_a_while(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    await action(hass, "set_override", preset="eco", duration={"hours": 2})
    assert setpoint(hass) == ("heat", 18.0)
    assert mode(hass) == "timed"
    set_inputs(hass, ground_floor="off")  # a plan change does not end it
    await hass.async_block_till_done()
    set_inputs(hass, ground_floor="on")
    await hass.async_block_till_done()
    assert mode(hass) == "timed"
    await advance(hass, freezer, 2 * 3600)
    assert setpoint(hass) == ("heat", 21.0)


async def test_an_override_until_a_time_that_has_passed_today_lasts_until_tomorrow(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(
        dt_util.as_utc(dt_util.now().replace(hour=20, minute=0, second=0, microsecond=0))
    )
    await setup_house()
    await action(hass, "set_override", temperature=19.5, until="18:00:00")
    parsed = dt_util.parse_datetime(attribute(hass, MODE, "override_until"))
    assert parsed is not None
    until = dt_util.as_local(parsed)
    assert (until - dt_util.now()).total_seconds() == 22 * 3600
    assert (until.hour, until.minute) == (18, 0)
    assert setpoint(hass) == ("heat", 19.5)


async def test_an_override_until_the_next_change_is_a_hold(
    hass: HomeAssistant, setup_house: Setup
) -> None:
    await setup_house()
    await action(hass, "set_override", temperature=23)
    assert mode(hass) == "manual"
    set_inputs(hass, ground_floor="off")
    await hass.async_block_till_done()
    assert mode(hass) == "idle"


@pytest.mark.parametrize(
    "data",
    [
        {"temperature": 22, "preset": "eco"},
        {},
        {"temperature": 22, "until": "18:00", "duration": 60},
    ],
)
async def test_an_override_needs_one_target_and_at_most_one_end(
    hass: HomeAssistant, setup_house: Setup, data: dict[str, Any]
) -> None:
    await setup_house()
    with pytest.raises((ServiceValidationError, vol.Invalid)):
        await action(hass, "set_override", **data)
    assert mode(hass) == "schedule"


async def test_extend_block_keeps_comfort_after_the_block_ends(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    later = dt_util.as_local(dt_util.utcnow() + timedelta(hours=1))
    await action(hass, "extend_block", until=later.strftime("%H:%M:%S"))
    set_inputs(hass, ground_floor="off")  # the block ends
    await hass.async_block_till_done()
    assert setpoint(hass) == ("heat", 21.0)
    assert mode(hass) == "timed"
    await advance(hass, freezer, 3600)
    assert setpoint(hass) == ("heat", 18.0)


async def test_the_room_thermostats_presets(hass: HomeAssistant, setup_house: Setup) -> None:
    await setup_house()

    async def preset(name: str) -> None:
        await hass.services.async_call(
            "climate", "set_preset_mode", {"entity_id": ROOM, "preset_mode": name}, blocking=True
        )
        await hass.async_block_till_done()

    await preset("eco")
    assert setpoint(hass) == ("heat", 18.0)
    assert (attribute(hass, ROOM, "preset_mode"), mode(hass)) == ("eco", "manual")
    await preset("boost")
    assert setpoint(hass) == ("heat", 30.0)
    await preset("none")  # ends the boost and the preset's hold
    assert setpoint(hass) == ("heat", 21.0)
    assert (attribute(hass, ROOM, "preset_mode"), mode(hass)) == ("none", "schedule")


async def test_a_boost_for_a_whole_area(hass: HomeAssistant, setup_house: Setup) -> None:
    await setup_house()
    await hass.services.async_call(DOMAIN, "boost", {"area_id": "kitchen"}, blocking=True)
    await hass.async_block_till_done()
    assert mode(hass) == "boost"
