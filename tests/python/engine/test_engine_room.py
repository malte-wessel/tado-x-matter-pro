# mypy: disable-error-code="comparison-overlap,unreachable"
"""Tests for the room reducer."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.tado_x_matter_pro.engine.model import (
    Desired,
    Expiry,
    Inputs,
    Mode,
    Override,
    RoomConfig,
    RoomState,
    WindowPhase,
)
from custom_components.tado_x_matter_pro.engine.room import (
    EndPreset,
    Event,
    ExtendBlock,
    ExternalChange,
    NumberChanged,
    Resume,
    SetMode,
    SetOverride,
    SetTemperature,
    StartBoost,
    Step,
    step,
)

T0 = datetime(2026, 10, 27, 16, 0, tzinfo=UTC)
CONFIG = RoomConfig(
    open_delay=timedelta(seconds=30), close_delay=timedelta(minutes=5), frost_temperature=7.0
)
BLOCK = Inputs(
    schedule_on=True,
    block_temperature=None,
    idle=False,
    heating_temperature=21.0,
    idle_temperature=18.0,
    window_open=False,
    room_temperature=20.0,
)


class Room:
    """Drives the reducer like the controller does: one state, moving time."""

    def __init__(self, inputs: Inputs = BLOCK, state: RoomState | None = None) -> None:
        self.inputs = inputs
        self.state = state or RoomState()
        self.now = T0
        self.last: Step = self.run()

    def run(self, event: Event | None = None, **changes: object) -> Step:
        if changes:
            self.inputs = replace(self.inputs, **changes)  # type: ignore[arg-type]
        self.last = step(self.state, self.inputs, CONFIG, self.now, event)
        self.state = self.last.state
        return self.last

    def at(self, seconds: float) -> Step:
        self.now = T0 + timedelta(seconds=seconds)
        return self.run()

    @property
    def desired(self) -> Desired:
        return self.last.desired


@pytest.mark.parametrize(
    ("inputs", "expected", "mode"),
    [
        (BLOCK, 21.0, Mode.SCHEDULE),
        (replace(BLOCK, block_temperature=22.5), 22.5, Mode.SCHEDULE),
        (replace(BLOCK, schedule_on=False), 18.0, Mode.ECO),
        (replace(BLOCK, idle=True, block_temperature=22.5), 18.0, Mode.ECO),
        (replace(BLOCK, heating_temperature=21.3), 21.5, Mode.SCHEDULE),
        (replace(BLOCK, block_temperature=35.0), 30.0, Mode.SCHEDULE),  # what thermostats take
    ],
)
def test_plan_ladder(inputs: Inputs, expected: float, mode: Mode) -> None:
    desired = Room(inputs).desired
    assert (desired.hvac_mode, desired.temperature, desired.mode) == ("heat", expected, mode)


def test_short_window_opening_is_ignored() -> None:
    room = Room()
    room.run(window_open=True)
    assert room.state.window is WindowPhase.OPENING
    assert room.desired.hvac_mode == "heat"
    assert room.last.next_wakeup == T0 + timedelta(seconds=30)
    room.now = T0 + timedelta(seconds=5)
    room.run(window_open=False)
    assert room.state.window is WindowPhase.CLOSED
    assert room.desired.hvac_mode == "heat"
    assert room.state.bounces == [room.now]


def test_window_cycle_switches_off_waits_and_resumes() -> None:
    room = Room()
    room.run(window_open=True)
    assert room.at(30).desired.mode is Mode.WINDOW
    assert room.desired.hvac_mode == "off"

    room.now = T0 + timedelta(minutes=10)
    room.run(window_open=False)
    assert room.desired.mode is Mode.WAITING
    assert room.desired.resume_at == room.now + timedelta(minutes=5)

    assert room.at(15 * 60).desired.mode is Mode.SCHEDULE
    assert room.desired.hvac_mode == "heat"


def test_reopening_while_waiting_switches_off_at_once() -> None:
    room = Room()
    room.run(window_open=True)
    room.at(30)
    room.now = T0 + timedelta(seconds=60)
    room.run(window_open=False)
    room.now = T0 + timedelta(seconds=90)
    room.run(window_open=True)
    assert room.state.window is WindowPhase.OPEN
    assert room.desired.mode is Mode.WINDOW


def test_manual_hold_lasts_until_the_next_plan_change() -> None:
    room = Room()
    room.run(ExternalChange("heat", 23.0))
    assert (room.desired.temperature, room.desired.mode) == (23.0, Mode.MANUAL)
    # attribute-only schedule updates (same plan key) keep the hold
    room.run(room_temperature=21.0)
    assert room.desired.mode is Mode.MANUAL
    room.run(schedule_on=False)
    assert (room.desired.temperature, room.desired.mode) == (18.0, Mode.ECO)


def test_away_clears_a_manual_hold() -> None:
    room = Room()
    room.run(SetTemperature(24.0))
    room.run(idle=True)
    assert room.desired.mode is Mode.ECO


def test_changing_a_temperature_number_clears_a_hold() -> None:
    room = Room()
    room.run(SetTemperature(24.0))
    room.run(NumberChanged(), idle_temperature=17.0)  # also the one the block does not use
    assert (room.desired.temperature, room.desired.mode) == (21.0, Mode.SCHEDULE)
    room.run(SetTemperature(24.0))
    room.run(NumberChanged(), heating_temperature=22.0)
    assert (room.desired.temperature, room.desired.mode) == (22.0, Mode.SCHEDULE)


def test_a_number_change_keeps_a_room_that_is_switched_off() -> None:
    room = Room()
    room.run(SetMode("off"))
    room.run(NumberChanged(), heating_temperature=22.0)
    assert room.desired.mode is Mode.OFF


def test_dial_while_window_open_heats_until_the_next_opening() -> None:
    room = Room()
    room.run(window_open=True)
    room.at(30)
    room.run(ExternalChange("heat", 22.0))
    assert (room.desired.hvac_mode, room.desired.mode) == ("heat", Mode.MANUAL)
    room.now = T0 + timedelta(seconds=60)
    room.run(window_open=False)
    assert room.desired.mode is Mode.MANUAL  # waiting does not switch it off either
    room.now = T0 + timedelta(seconds=90)
    room.run(window_open=True)
    assert room.desired.mode is Mode.WINDOW


def test_dial_while_waiting_ends_the_wait() -> None:
    room = Room()
    room.run(window_open=True)
    room.at(30)
    room.now = T0 + timedelta(seconds=60)
    room.run(window_open=False)
    room.run(ExternalChange("heat", 20.0))
    assert room.state.window is WindowPhase.CLOSED
    assert (room.desired.temperature, room.desired.mode) == (20.0, Mode.MANUAL)


def test_external_off_holds_off_until_the_next_change() -> None:
    room = Room()
    room.run(ExternalChange("off", None))
    assert (room.desired.hvac_mode, room.desired.mode) == ("off", Mode.OFF)
    room.run(schedule_on=False)
    assert room.desired.mode is Mode.ECO


def test_room_off_survives_plan_changes_until_resume() -> None:
    room = Room()
    room.run(SetMode("off"))
    room.run(schedule_on=False)
    assert room.desired.mode is Mode.OFF
    room.run(Resume())
    assert room.desired.mode is Mode.ECO


def test_mode_heat_holds_the_current_target_and_auto_releases_it() -> None:
    room = Room()
    room.run(SetMode("heat"))
    assert (room.desired.temperature, room.desired.mode) == (21.0, Mode.MANUAL)
    room.run(SetMode("auto"))
    assert room.desired.mode is Mode.SCHEDULE


def test_resume_skips_the_wait_but_not_an_open_window() -> None:
    room = Room()
    room.run(window_open=True)
    room.at(30)
    room.run(Resume())
    assert room.desired.mode is Mode.WINDOW
    room.now = T0 + timedelta(seconds=60)
    room.run(window_open=False)
    room.run(Resume())
    assert room.desired.mode is Mode.SCHEDULE


def test_timed_override_expires() -> None:
    until = T0 + timedelta(hours=1)
    room = Room(state=RoomState(override=Override(23.0, until)))
    assert room.desired.override_until == until
    assert room.last.next_wakeup == until
    room.run(schedule_on=False)  # a plan change keeps a timed override
    assert room.desired.temperature == 23.0
    assert room.at(3600).desired.mode is Mode.ECO


def test_frost_floor_with_hysteresis() -> None:
    room = Room(replace(BLOCK, room_temperature=6.5))
    room.run(SetMode("off"))
    assert (room.desired.hvac_mode, room.desired.temperature, room.desired.mode) == (
        "heat",
        7.0,
        Mode.FROST,
    )
    room.run(room_temperature=7.5)
    assert room.desired.mode is Mode.FROST
    room.run(room_temperature=8.0)
    assert room.desired.mode is Mode.OFF


def test_heat_targets_never_go_below_frost() -> None:
    room = Room(replace(BLOCK, idle=True, idle_temperature=5.0))
    assert room.desired.temperature == 7.0


def test_open_delay_zero_switches_off_at_once() -> None:
    state = step(
        RoomState(), replace(BLOCK, window_open=True), replace(CONFIG, open_delay=timedelta()), T0
    )
    assert state.desired.mode is Mode.WINDOW


def test_never_expiring_override_keeps_no_wakeup() -> None:
    room = Room(state=RoomState(override=Override(None, Expiry.NEVER)))
    assert room.last.next_wakeup is None


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_boost_is_a_layer_above_a_hold() -> None:
    room = Room()
    room.run(SetOverride(23.0))
    room.run(StartBoost(30.0, at(30)))
    assert (room.desired.temperature, room.desired.mode) == (30.0, Mode.BOOST)
    assert room.desired.boost_until == at(30)
    assert room.last.next_wakeup == at(30)
    room.run(schedule_on=False)  # a plan change ends the hold underneath, not the boost
    assert room.desired.mode is Mode.BOOST
    room.at(30 * 60)
    assert (room.desired.temperature, room.desired.mode) == (18.0, Mode.ECO)


def test_boost_ends_on_resume_and_on_a_change_by_hand() -> None:
    room = Room()
    room.run(StartBoost(30.0, at(30)))
    room.run(Resume())
    assert room.desired.mode is Mode.SCHEDULE
    room.run(StartBoost(30.0, at(30)))
    room.run(ExternalChange("heat", 22.0))
    assert (room.desired.temperature, room.desired.mode) == (22.0, Mode.MANUAL)


def test_an_open_window_beats_a_boost() -> None:
    room = Room()
    room.run(StartBoost(30.0, at(30)))
    room.run(window_open=True)
    room.at(30)
    assert (room.desired.hvac_mode, room.desired.mode) == ("off", Mode.WINDOW)
    assert room.desired.boost_until == at(30)


def test_a_timed_override_runs_until_its_time_and_survives_plan_changes() -> None:
    room = Room()
    room.run(SetOverride(18.0, at(60)))
    assert (room.desired.temperature, room.desired.mode) == (18.0, Mode.TIMED)
    assert room.desired.override_until == at(60)
    room.run(schedule_on=False)
    room.run(schedule_on=True)
    assert room.desired.mode is Mode.TIMED
    room.at(60 * 60)
    assert (room.desired.temperature, room.desired.mode) == (21.0, Mode.SCHEDULE)


def test_extend_block_keeps_the_current_plan_temperature() -> None:
    room = Room()
    room.run(ExtendBlock(at(120)))
    room.run(schedule_on=False)  # the block ends, the extension keeps 21
    assert (room.desired.temperature, room.desired.mode) == (21.0, Mode.TIMED)
    room.at(120 * 60)
    assert (room.desired.temperature, room.desired.mode) == (18.0, Mode.ECO)


def test_preset_none_ends_a_boost_and_a_presets_hold_but_not_other_holds() -> None:
    room = Room()
    room.run(SetOverride(18.0, preset="eco"))
    room.run(StartBoost(30.0, at(30)))
    room.run(EndPreset())
    assert room.desired.mode is Mode.SCHEDULE
    room.run(SetTemperature(23.0))
    room.run(EndPreset())
    assert (room.desired.temperature, room.desired.mode) == (23.0, Mode.MANUAL)


REMIND = replace(CONFIG, remind_after=timedelta(minutes=30), remind_below=12.0)


def test_a_window_open_too_long_is_reminded_once_per_opening() -> None:
    inputs = replace(BLOCK, window_open=True, outdoor_temperature=5.0)
    state = step(RoomState(), inputs, REMIND, T0).state
    result = step(state, inputs, REMIND, at(0.5))  # open: off
    assert result.next_wakeup == at(30.5)
    result = step(result.state, inputs, REMIND, at(30.5))
    assert result.desired.window_overdue
    assert result.state.reminded
    result = step(result.state, replace(inputs, window_open=False), REMIND, at(31))
    assert not result.desired.window_overdue
    assert not result.state.reminded  # a new opening is reminded again


def test_no_reminder_while_it_is_warm_outside_but_still_overdue() -> None:
    warm = replace(BLOCK, window_open=True, outdoor_temperature=15.0)
    state = step(RoomState(), warm, REMIND, T0).state
    result = step(step(state, warm, REMIND, at(0.5)).state, warm, REMIND, at(30.5))
    assert result.desired.window_overdue
    assert not result.state.reminded
    colder = step(result.state, replace(warm, outdoor_temperature=10.0), REMIND, at(40))
    assert colder.state.reminded


def test_no_reminder_without_a_reminder_time() -> None:
    inputs = replace(BLOCK, window_open=True)
    state = step(RoomState(), inputs, CONFIG, T0).state
    result = step(step(state, inputs, CONFIG, at(0.5)).state, inputs, CONFIG, at(600))
    assert not result.desired.window_overdue
    assert not result.state.reminded


def test_a_new_override_ends_a_boost() -> None:
    room = Room()
    room.run(StartBoost(30.0, at(30)))
    room.run(SetOverride(18.0, preset="eco"))
    assert (room.desired.temperature, room.desired.mode) == (18.0, Mode.MANUAL)
    room.run(StartBoost(30.0, at(30)))
    room.run(ExtendBlock(at(60)))
    assert (room.desired.temperature, room.desired.mode) == (21.0, Mode.TIMED)


def test_a_temperature_set_while_a_window_is_open_heats_until_the_next_opening() -> None:
    room = Room()
    room.run(window_open=True)
    room.at(30)
    assert room.desired.mode is Mode.WINDOW
    room.run(SetOverride(22.0, preset="comfort"))  # a preset, set_override: like a dial
    assert (room.desired.hvac_mode, room.desired.temperature) == ("heat", 22.0)
    room.run(StartBoost(30.0, at(60)))  # a boost waits for the window
    room.run(EndPreset())
    room.run(window_open=False)
    room.at(31)
    room.run(window_open=True)
    room.at(62)
    assert room.desired.mode is Mode.WINDOW


def test_while_away_a_block_edge_keeps_a_hold() -> None:
    room = Room(replace(BLOCK, idle=True))
    room.run(SetTemperature(22.0))
    room.run(schedule_on=False)  # the block ends, but away keeps eco: nothing changes
    assert (room.desired.temperature, room.desired.mode) == (22.0, Mode.MANUAL)
    room.run(idle=False)  # away ends: a real change
    assert (room.desired.temperature, room.desired.mode) == (18.0, Mode.ECO)


def test_preset_none_ends_a_timed_override() -> None:
    room = Room()
    room.run(SetOverride(18.0, at(120)))
    room.run(EndPreset())
    assert room.desired.mode is Mode.SCHEDULE
