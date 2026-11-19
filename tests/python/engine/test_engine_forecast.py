"""When the room's target changes next by itself, and to what."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from custom_components.tado_x_matter_pro.engine.forecast import Block, Forecast, forecast
from custom_components.tado_x_matter_pro.engine.model import Inputs, RoomConfig, RoomState
from custom_components.tado_x_matter_pro.engine.room import (
    Event,
    SetMode,
    SetOverride,
    SetTemperature,
    StartBoost,
    step,
)

T0 = datetime(2026, 11, 18, 16, 0, tzinfo=UTC)  # inside the block 14:00–23:00
CONFIG = RoomConfig(open_delay=timedelta(seconds=30), close_delay=timedelta(minutes=5))
BLOCK = Inputs(
    schedule_on=True,
    block_temperature=None,
    idle=False,
    heating_temperature=21.0,
    idle_temperature=18.0,
    window_open=False,
    room_temperature=20.0,
)
EVENING = [Block(T0 - timedelta(hours=2), T0 + timedelta(hours=7))]


def h(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def next_change(
    *events: Event,
    inputs: Inputs = BLOCK,
    blocks: list[Block] = EVENING,
    now: datetime = T0,
) -> Forecast | None:
    state = RoomState()
    result = step(state, inputs, CONFIG, now)
    for event in events:
        result = step(result.state, inputs, CONFIG, now, event)
    return forecast(result.state, inputs, CONFIG, now, desired=result.desired, blocks=blocks)


def test_the_block_ends() -> None:
    assert next_change() == Forecast(h(7), 18.0)


def test_a_block_continuing_past_midnight_is_no_change() -> None:
    midnight = h(8)
    blocks = [Block(h(-2), midnight), Block(midnight, h(14))]
    assert next_change(blocks=blocks) == Forecast(h(14), 18.0)


def test_the_next_block_brings_its_own_temperature() -> None:
    idle = replace(BLOCK, schedule_on=False)
    assert next_change(inputs=idle, blocks=[Block(h(1), h(3), 22.5)]) == Forecast(h(1), 22.5)


def test_a_hold_ends_at_the_next_plan_change() -> None:
    assert next_change(SetTemperature(23.0)) == Forecast(h(7), 18.0)


def test_a_timed_override_ends_at_its_time() -> None:
    assert next_change(SetOverride(19.0, h(2))) == Forecast(h(2), 21.0)


def test_a_boost_falls_back_to_what_lies_underneath() -> None:
    assert next_change(SetTemperature(23.0), StartBoost(30.0, h(0.5))) == Forecast(h(0.5), 23.0)


def test_nothing_changes_by_itself_while_away_while_off_or_with_a_window_open() -> None:
    assert next_change(inputs=replace(BLOCK, idle=True)) is None
    assert next_change(SetMode("off")) is None
    window = replace(BLOCK, window_open=True)
    state = step(RoomState(), window, CONFIG, T0).state
    result = step(state, window, CONFIG, T0 + timedelta(seconds=30))
    later = T0 + timedelta(seconds=30)
    assert (
        forecast(result.state, window, CONFIG, later, desired=result.desired, blocks=EVENING)
        is None
    )


def test_after_a_window_the_wait_ends() -> None:
    window = replace(BLOCK, window_open=True)
    state = step(RoomState(), window, CONFIG, T0).state
    state = step(state, window, CONFIG, T0 + timedelta(seconds=30)).state  # open: off
    closed_at = T0 + timedelta(minutes=1)
    result = step(state, BLOCK, CONFIG, closed_at)  # closed: the wait runs
    coming = forecast(
        result.state, BLOCK, CONFIG, closed_at, desired=result.desired, blocks=EVENING
    )
    assert coming == Forecast(closed_at + timedelta(minutes=5), 21.0)


def test_without_the_blocks_only_deadlines_are_known() -> None:
    assert next_change(blocks=[]) is None
    assert next_change(SetOverride(19.0, h(2)), blocks=[]) == Forecast(h(2), 21.0)
