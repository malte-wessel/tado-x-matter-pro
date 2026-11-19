"""Writes reach the thermostats despite drop-outs, late deliveries and calls that hang."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.tado_x_matter_pro.const import DOMAIN
from tests.python.conftest import FakeTrv, set_inputs

type Setup = Callable[..., Awaitable[MockConfigEntry]]
KITCHEN_TRV = "climate.kitchen_trv"
ISSUE = f"unconfirmed_{KITCHEN_TRV}"


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def setpoint(hass: HomeAssistant, entity_id: str) -> tuple[str, float | None]:
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state, state.attributes.get("temperature")


def mode(hass: HomeAssistant, room: str) -> str:
    state = hass.states.get(f"sensor.{room}_mode")
    assert state is not None
    return state.state


async def test_a_schedule_edge_spreads_the_rooms_writes(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    with patch(
        "custom_components.tado_x_matter_pro.controller.random_delay",
        side_effect=[timedelta(seconds=10), timedelta(seconds=30)],
    ):
        set_inputs(hass, ground_floor="off", bathroom="on")  # one edge for both rooms
        await hass.async_block_till_done()
    assert mode(hass, "kitchen_heating") == "eco"  # decided at once, written later
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 21.0)

    await advance(hass, freezer, 10)
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 18.0)
    assert setpoint(hass, "climate.bath_trv") == ("heat", 18.0)

    await advance(hass, freezer, 20)
    assert setpoint(hass, "climate.bath_trv") == ("heat", 21.0)
    assert setpoint(hass, "climate.bath_tub_trv") == ("heat", 21.0)


async def test_people_and_windows_are_not_kept_waiting(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    with patch(
        "custom_components.tado_x_matter_pro.controller.random_delay",
        return_value=timedelta(seconds=30),
    ) as delay:
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": "climate.kitchen_heating", "temperature": 23},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert setpoint(hass, KITCHEN_TRV) == ("heat", 23.0)
        set_inputs(hass, kitchen_window="on")
        await hass.async_block_till_done()
        await advance(hass, freezer, 30)  # the open delay, nothing more
        assert setpoint(hass, KITCHEN_TRV)[0] == "off"
        delay.assert_not_called()


async def test_a_write_that_does_not_arrive_is_sent_again(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    kitchen = trvs[KITCHEN_TRV]
    kitchen.lose_writes = True
    before = len(kitchen.writes)
    set_inputs(hass, ground_floor="off", bathroom="on")
    await hass.async_block_till_done()
    # the bathroom's thermostats do not wait for the kitchen's
    assert setpoint(hass, "climate.bath_trv") == ("heat", 21.0)
    assert setpoint(hass, "climate.bath_tub_trv") == ("heat", 21.0)

    attempts = []
    for seconds in (0, 60, 120, 420, 60):  # attempts at 0, +1, +3, +10 min, then it gives up
        await advance(hass, freezer, seconds)
        attempts.append(len(kitchen.writes) - before)
    assert attempts == [1, 2, 3, 4, 4]
    assert kitchen.writes[-1] == ("heat", 18.0)

    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, ISSUE) is None
    await advance(hass, freezer, 20 * 60)  # 30 minutes unconfirmed
    assert issues.async_get_issue(DOMAIN, ISSUE) is not None

    kitchen.lose_writes = False  # the link is back; its next report sends again
    kitchen.read(19.0)
    await hass.async_block_till_done()
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 18.0)
    assert issues.async_get_issue(DOMAIN, ISSUE) is None


async def test_a_thermostat_that_was_unavailable_gets_the_change_when_it_returns(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    kitchen = trvs[KITCHEN_TRV]
    kitchen.drop_out(available=False)
    before = len(kitchen.writes)
    set_inputs(hass, ground_floor="off")
    await hass.async_block_till_done()
    await advance(hass, freezer, 15 * 60)
    assert len(kitchen.writes) == before  # Home Assistant would drop calls to it anyway

    kitchen.drop_out(available=True)
    await hass.async_block_till_done()
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 18.0)
    assert mode(hass, "kitchen_heating") == "eco"


async def test_a_dial_turned_while_the_thermostat_was_unavailable_is_a_hold(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    kitchen = trvs[KITCHEN_TRV]
    kitchen.drop_out(available=False)
    kitchen.dial(23.0)  # at the device; Home Assistant cannot see it
    await hass.async_block_till_done()

    kitchen.drop_out(available=True)
    await hass.async_block_till_done()
    await advance(hass, freezer, 4)
    assert mode(hass, "kitchen_heating") == "manual"
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 23.0)


async def test_a_late_delivery_of_an_older_write_is_not_a_manual_change(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    kitchen = trvs[KITCHEN_TRV]
    kitchen.queue_writes = True  # the Matter server holds the write
    set_inputs(hass, ground_floor="off")  # 18 is sent, but does not arrive yet
    await hass.async_block_till_done()
    set_inputs(hass, ground_floor="on")  # back to 21, which the thermostat still shows
    await hass.async_block_till_done()

    kitchen.queue_writes = False
    kitchen.deliver()  # the old 18 arrives late
    await hass.async_block_till_done()
    await advance(hass, freezer, 4)
    assert mode(hass, "kitchen_heating") == "schedule"
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 21.0)


async def test_a_change_at_the_thermostat_while_our_write_is_pending_is_a_hold(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    kitchen = trvs[KITCHEN_TRV]
    kitchen.lose_writes = True
    set_inputs(hass, ground_floor="off")  # 18 is sent and lost; retries are due
    await hass.async_block_till_done()
    kitchen.dial(23.0)
    await hass.async_block_till_done()
    await advance(hass, freezer, 4)
    assert mode(hass, "kitchen_heating") == "manual"
    writes = len(kitchen.writes)

    await advance(hass, freezer, 15 * 60)
    assert len(kitchen.writes) == writes  # no more 18
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 23.0)


async def test_a_call_that_hangs_blocks_neither_the_room_nor_other_rooms(
    hass: HomeAssistant, setup_house: Setup, trvs: dict[str, FakeTrv]
) -> None:
    await setup_house()
    kitchen = trvs[KITCHEN_TRV]
    kitchen.hang = asyncio.Event()
    for temperature in (23, 24):  # the service returns at once, also the second time
        await asyncio.wait_for(
            hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": "climate.kitchen_heating", "temperature": temperature},
                blocking=True,
            ),
            timeout=1,
        )
    set_inputs(hass, bathroom="on")
    for _ in range(20):  # let the loop run; waiting for all tasks would wait for the hang
        await asyncio.sleep(0)
    assert setpoint(hass, "climate.bath_trv") == ("heat", 21.0)
    assert kitchen.writes[-1] == ("heat", 23.0)  # one call at a time

    kitchen.hang.set()
    await hass.async_block_till_done()
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 24.0)  # the latest wins


async def test_a_late_two_part_delivery_on_the_way_back_from_a_window_is_no_hold(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    kitchen = trvs[KITCHEN_TRV]
    set_inputs(hass, kitchen_window="on")
    await advance(hass, freezer, 30)  # off, setpoint stays 21
    set_inputs(hass, ground_floor="off")  # the plan changes during the opening: 18 after it
    await hass.async_block_till_done()
    kitchen.queue_writes = True  # the Matter server holds what comes next
    set_inputs(hass, kitchen_window="off")
    await hass.async_block_till_done()
    await advance(hass, freezer, 5 * 60)  # the wait ends: heat at 18, held
    await advance(hass, freezer, 60)  # the retry, held too
    await advance(hass, freezer, 60)  # long past "on the way"
    kitchen.queue_writes = False
    kitchen.deliver()  # mode first (heat at the old 21), then the setpoint (18)
    await hass.async_block_till_done()
    await advance(hass, freezer, 5)
    assert mode(hass, "kitchen_heating") == "eco"
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 18.0)
    assert kitchen.writes[-1] != ("heat", 21.0)


async def test_a_late_delivery_to_a_thermostat_unavailable_at_a_restart_is_no_hold(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    entry = await setup_house()
    kitchen = trvs[KITCHEN_TRV]
    kitchen.queue_writes = True
    set_inputs(hass, ground_floor="off")  # 18 is sent and held
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    kitchen.drop_out(available=False)
    kitchen.queue_writes = False
    kitchen.deliver()  # 18 lands while Home Assistant is down and the thermostat away
    set_inputs(hass, ground_floor="on")  # meanwhile the plan wants 21 again
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    kitchen.drop_out(available=True)  # back with 18: ours, not a change by someone
    await hass.async_block_till_done()
    await advance(hass, freezer, 5)
    assert mode(hass, "kitchen_heating") == "schedule"
    assert setpoint(hass, KITCHEN_TRV) == ("heat", 21.0)


async def test_a_silent_thermostat_gets_two_late_attempts_after_the_writer_gave_up(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    kitchen = trvs[KITCHEN_TRV]
    kitchen.lose_writes = True
    before = len(kitchen.writes)
    set_inputs(hass, ground_floor="off")
    await hass.async_block_till_done()
    for seconds in (60, 120, 420, 60):  # +1, +3, +10 min, then it gives up
        await advance(hass, freezer, seconds)
    assert len(kitchen.writes) - before == 4

    await advance(hass, freezer, 30 * 60)
    assert len(kitchen.writes) - before == 5
    await advance(hass, freezer, 30 * 60)
    assert len(kitchen.writes) - before == 6
    await advance(hass, freezer, 3 * 3600)  # not a periodic tick: nothing more on its own
    assert len(kitchen.writes) - before == 6
