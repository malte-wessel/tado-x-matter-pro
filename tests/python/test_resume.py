"""Back to the schedule: per room (action, button) and for all rooms at once."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.tado_x_matter_pro.const import DOMAIN
from tests.python.conftest import FakeTrv, set_inputs

type Setup = Callable[..., Awaitable[MockConfigEntry]]
OFF_SCHEDULE = "sensor.heating_rooms_off_schedule"


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def mode(hass: HomeAssistant, room: str) -> str:
    state = hass.states.get(f"sensor.{room}_mode")
    assert state is not None
    return state.state


def setpoint(hass: HomeAssistant, entity_id: str) -> tuple[str, float | None]:
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state, state.attributes.get("temperature")


async def hold(hass: HomeAssistant, room: str, temperature: float) -> None:
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": f"climate.{room}", "temperature": temperature},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_resume_ends_a_hold_and_counts_the_rooms_off_schedule(
    hass: HomeAssistant, setup_house: Setup
) -> None:
    await setup_house()
    assert hass.states.get(OFF_SCHEDULE).state == "0"  # type: ignore[union-attr]
    await hold(hass, "kitchen_heating", 23)
    await hass.services.async_call(
        "climate", "turn_off", {"entity_id": "climate.bathroom"}, blocking=True
    )
    await hass.async_block_till_done()
    count = hass.states.get(OFF_SCHEDULE)
    assert count is not None
    assert count.state == "2"
    assert count.attributes["rooms"] == {"Kitchen": "manual", "Bathroom": "off"}

    await hass.services.async_call(
        DOMAIN, "resume_schedule", {"entity_id": "climate.kitchen_heating"}, blocking=True
    )
    await hass.async_block_till_done()
    assert mode(hass, "kitchen_heating") == "schedule"
    assert setpoint(hass, "climate.kitchen_trv") == ("heat", 21.0)
    assert hass.states.get(OFF_SCHEDULE).state == "1"  # type: ignore[union-attr]


async def test_the_house_button_resumes_every_room(hass: HomeAssistant, setup_house: Setup) -> None:
    await setup_house()
    await hold(hass, "kitchen_heating", 23)
    await hold(hass, "bathroom", 24)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.heating_resume_all_rooms"}, blocking=True
    )
    await hass.async_block_till_done()
    assert (mode(hass, "kitchen_heating"), mode(hass, "bathroom")) == ("schedule", "idle")
    assert hass.states.get(OFF_SCHEDULE).state == "0"  # type: ignore[union-attr]


async def test_the_room_button_resumes_that_room(hass: HomeAssistant, setup_house: Setup) -> None:
    await setup_house()
    await hold(hass, "kitchen_heating", 23)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.kitchen_heating_resume_schedule"}, blocking=True
    )
    await hass.async_block_till_done()
    assert mode(hass, "kitchen_heating") == "schedule"


async def test_resume_while_a_window_is_open_keeps_the_room_off_then_follows_the_plan(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    await hold(hass, "kitchen_heating", 23)
    set_inputs(hass, kitchen_window="on")
    await hass.async_block_till_done()
    await advance(hass, freezer, 30)
    await hass.services.async_call(
        DOMAIN, "resume_schedule", {"entity_id": "climate.kitchen_heating"}, blocking=True
    )
    await hass.async_block_till_done()
    assert mode(hass, "kitchen_heating") == "window"
    assert setpoint(hass, "climate.kitchen_trv")[0] == "off"

    set_inputs(hass, kitchen_window="off")
    await hass.async_block_till_done()
    await advance(hass, freezer, 5 * 60)
    assert setpoint(hass, "climate.kitchen_trv") == ("heat", 21.0)  # the plan, not the old 23


async def test_resume_during_the_wait_after_a_window_applies_the_plan_at_once(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    await hold(hass, "kitchen_heating", 23)
    set_inputs(hass, kitchen_window="on")
    await hass.async_block_till_done()
    await advance(hass, freezer, 30)
    set_inputs(hass, kitchen_window="off")
    await hass.async_block_till_done()
    assert mode(hass, "kitchen_heating") == "waiting"
    await hass.services.async_call(
        DOMAIN, "resume_schedule", {"entity_id": "climate.kitchen_heating"}, blocking=True
    )
    await hass.async_block_till_done()
    assert mode(hass, "kitchen_heating") == "schedule"
    assert setpoint(hass, "climate.kitchen_trv") == ("heat", 21.0)


async def test_resume_with_an_area_target_reaches_only_the_room_thermostat(
    hass: HomeAssistant, setup_house: Setup, trvs: dict[str, FakeTrv]
) -> None:
    await setup_house()  # the kitchen thermostat and its room device are in the area "Kitchen"
    await hold(hass, "kitchen_heating", 23)
    await hass.services.async_call(DOMAIN, "resume_schedule", {"area_id": "kitchen"}, blocking=True)
    await hass.async_block_till_done()
    assert mode(hass, "kitchen_heating") == "schedule"


async def test_resume_returns_at_once_while_a_thermostat_hangs(
    hass: HomeAssistant, setup_house: Setup, trvs: dict[str, FakeTrv]
) -> None:
    await setup_house()
    await hold(hass, "kitchen_heating", 23)
    trvs["climate.kitchen_trv"].hang = asyncio.Event()
    for _ in range(2):  # a second resume is not queued behind the first
        await asyncio.wait_for(
            hass.services.async_call(
                DOMAIN, "resume_schedule", {"entity_id": "climate.kitchen_heating"}, blocking=True
            ),
            timeout=1,
        )
    trvs["climate.kitchen_trv"].hang.set()
    await hass.async_block_till_done()
    assert setpoint(hass, "climate.kitchen_trv") == ("heat", 21.0)
