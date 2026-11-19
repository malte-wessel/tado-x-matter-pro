"""The room reducer: from state, inputs and an event to the new state and the desired output.

Pure: no Home Assistant, no clock. The caller passes `now` (aware UTC) and schedules a call at
`Step.next_wakeup`.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .model import (
    Boost,
    Desired,
    Expiry,
    Inputs,
    Mode,
    Override,
    RoomConfig,
    RoomState,
    WindowPhase,
    round_to_step,
)

BOUNCE_WINDOW = timedelta(hours=1)
# What the thermostats accept (Tado X: 5–30 °C).
MIN_SETPOINT = 5.0
MAX_SETPOINT = 30.0
FROST_HYSTERESIS = 1.0


@dataclass(frozen=True, slots=True)
class ExternalChange:
    """A thermostat changed by someone else (dial, tado° app, Home Assistant on the TRV)."""

    hvac_mode: str
    temperature: float | None


@dataclass(frozen=True, slots=True)
class SetTemperature:
    """The room thermostat's target was set: a manual hold."""

    temperature: float


@dataclass(frozen=True, slots=True)
class SetMode:
    """The room thermostat's mode was set: auto (plan), heat (hold) or off."""

    mode: str


@dataclass(frozen=True, slots=True)
class Resume:
    """Back to the schedule: ends overrides and the wait after a window closed."""


@dataclass(frozen=True, slots=True)
class NumberChanged:
    """The room's comfort or eco temperature changed: like a plan change, it ends a hold.

    Either one, also the one the plan does not use right now.
    """


@dataclass(frozen=True, slots=True)
class StartBoost:
    """Heat at `temperature` until `until`; ends early on resume or a change by hand."""

    temperature: float
    until: datetime


@dataclass(frozen=True, slots=True)
class SetOverride:
    """Heat at `temperature` until `until`, or – without one – until the next plan change."""

    temperature: float
    until: datetime | None = None
    preset: str | None = None  # "comfort" or "eco" when set by a preset


@dataclass(frozen=True, slots=True)
class ExtendBlock:
    """Keep the plan's current temperature until `until`, whatever the schedule says."""

    until: datetime


@dataclass(frozen=True, slots=True)
class EndPreset:
    """The room thermostat's preset "none": ends a boost and a preset's hold."""


type Change = ExternalChange | SetTemperature | SetMode | Resume | NumberChanged
type Command = StartBoost | SetOverride | ExtendBlock | EndPreset
type Event = Change | Command


@dataclass(frozen=True, slots=True)
class Step:
    """The result of one step."""

    state: RoomState
    desired: Desired
    next_wakeup: datetime | None


def plan_target(inputs: Inputs) -> float:
    """Return the plan's temperature: idle, the block's own temperature, or the heating one."""
    if inputs.idle or not inputs.schedule_on:
        return inputs.idle_temperature
    if inputs.block_temperature is not None:
        # a typo in a block's additional data must not reach the thermostats
        return min(MAX_SETPOINT, max(MIN_SETPOINT, inputs.block_temperature))
    return inputs.heating_temperature


def plan_key(inputs: Inputs) -> tuple[bool, float | None, bool, float]:
    """Return what counts as a plan change: block on/off, its temperature, idle, the target."""
    return (inputs.schedule_on, inputs.block_temperature, inputs.idle, plan_target(inputs))


def step(
    state: RoomState,
    inputs: Inputs,
    config: RoomConfig,
    now: datetime,
    event: Event | None = None,
) -> Step:
    """Advance the room: plan changes, expiries, windows, the event; then decide."""
    new = deepcopy(state)
    _apply_plan_change(new, inputs, numbers_changed=isinstance(event, NumberChanged))
    _expire(new, now)
    _advance_window(new, config, now, window_open=inputs.window_open)
    if isinstance(event, StartBoost | SetOverride | ExtendBlock | EndPreset):
        _apply_command(new, event, inputs)
    elif event is not None:
        _apply_change(new, event, inputs)
    overdue = _remind(new, config, inputs, now)
    desired = replace(_decide(new, inputs, config), window_overdue=overdue)
    return Step(new, desired, _next_wakeup(new, config, now))


def _apply_plan_change(state: RoomState, inputs: Inputs, *, numbers_changed: bool) -> None:
    key = plan_key(inputs)
    if numbers_changed or (state.plan_key is not None and key != state.plan_key):
        override = state.override
        if override is not None and override.expires == Expiry.NEXT_CHANGE:
            state.override = None
    state.plan_key = key


def _expire(state: RoomState, now: datetime) -> None:
    override = state.override
    if override is not None and isinstance(override.expires, datetime) and now >= override.expires:
        state.override = None
    if state.boost is not None and now >= state.boost.until:
        state.boost = None


def _advance_window(
    state: RoomState, config: RoomConfig, now: datetime, *, window_open: bool
) -> None:
    state.bounces = [t for t in state.bounces if now - t < BOUNCE_WINDOW]
    while True:
        phase, deadline = state.window, state.window_deadline
        if phase is WindowPhase.CLOSED and window_open:
            _set_window(state, WindowPhase.OPENING, now + config.open_delay)
        elif phase is WindowPhase.OPENING and not window_open:
            _set_window(state, WindowPhase.CLOSED, None)
            state.bounces.append(now)
        elif phase is WindowPhase.OPENING and deadline is not None and now >= deadline:
            _open(state, now)
        elif phase is WindowPhase.OPEN and not window_open:
            _set_window(state, WindowPhase.WAITING, now + config.close_delay)
            state.window_open_since, state.reminded = None, False
        elif phase is WindowPhase.WAITING and window_open:
            _open(state, now)
        elif phase is WindowPhase.WAITING and deadline is not None and now >= deadline:
            _set_window(state, WindowPhase.CLOSED, None)
        else:
            return


def _open(state: RoomState, now: datetime) -> None:
    """Switch the room off for an open window: a new opening, as far as reminders go."""
    _set_window(state, WindowPhase.OPEN, None)
    _clear_window_ack(state)
    state.window_open_since, state.reminded = now, False


def _reminder_due(state: RoomState, config: RoomConfig) -> datetime | None:
    if config.remind_after is None or state.window_open_since is None:
        return None
    return state.window_open_since + config.remind_after


def _remind(state: RoomState, config: RoomConfig, inputs: Inputs, now: datetime) -> bool:
    """Return whether the window is open too long; mark the reminder sent when it is due."""
    due = _reminder_due(state, config)
    overdue = state.window is WindowPhase.OPEN and due is not None and now >= due
    below, outdoor = config.remind_below, inputs.outdoor_temperature
    cold = below is None or outdoor is None or outdoor < below
    if overdue and cold:
        state.reminded = True
    return overdue


def _set_window(state: RoomState, phase: WindowPhase, deadline: datetime | None) -> None:
    state.window = phase
    state.window_deadline = deadline


def _clear_window_ack(state: RoomState) -> None:
    if state.override is not None:
        state.override.window_ack = False


def _apply_command(state: RoomState, command: Command, inputs: Inputs) -> None:
    match command:
        case StartBoost(temperature=temperature, until=until):
            state.boost = Boost(round_to_step(temperature), until)
        case SetOverride(temperature=temperature, until=until, preset=preset):
            state.boost = None  # a new choice of temperature ends a boost
            state.override = Override(
                round_to_step(temperature), until or Expiry.NEXT_CHANGE, preset=preset
            )
        case ExtendBlock(until=until):
            state.boost = None
            state.override = Override(round_to_step(plan_target(inputs)), until)
        case _:  # EndPreset
            state.boost = None
            if state.override is not None and state.override.preset is not None:
                state.override = None


def _apply_change(state: RoomState, event: Change, inputs: Inputs) -> None:
    if not isinstance(event, NumberChanged):
        state.boost = None  # a change by hand, or resume, ends a boost
    match event:
        case ExternalChange(hvac_mode="off"):
            state.override = Override(None, Expiry.NEXT_CHANGE)
        case ExternalChange(temperature=temperature) if temperature is not None:
            _hold(state, temperature)
        case SetTemperature(temperature=temperature):
            _hold(state, temperature)
        case SetMode(mode="auto"):
            state.override = None
        case SetMode(mode="heat"):
            current = state.override.temperature if state.override else None
            _hold(state, current if current is not None else plan_target(inputs))
        case SetMode(mode="off"):
            state.override = Override(None, Expiry.NEVER)
        case Resume():
            state.override = None
            if state.window is WindowPhase.WAITING:
                _set_window(state, WindowPhase.CLOSED, None)
        case _:
            pass


def _hold(state: RoomState, temperature: float) -> None:
    """Hold until the next plan change; made while a window is open, the hold beats the window."""
    if state.window is WindowPhase.WAITING:
        _set_window(state, WindowPhase.CLOSED, None)
    state.override = Override(
        round_to_step(temperature),
        Expiry.NEXT_CHANGE,
        window_ack=state.window is WindowPhase.OPEN,
    )


def _decide(state: RoomState, inputs: Inputs, config: RoomConfig) -> Desired:
    target = round_to_step(plan_target(inputs))
    override = state.override
    until = override.expires if override and isinstance(override.expires, datetime) else None
    boost_until = state.boost.until if state.boost else None
    window_blocks = state.window in (WindowPhase.OPEN, WindowPhase.WAITING) and not (
        override is not None and override.window_ack
    )
    if window_blocks:
        waiting = state.window is WindowPhase.WAITING
        desired = Desired(
            "off",
            None,
            Mode.WAITING if waiting else Mode.WINDOW,
            target,
            resume_at=state.window_deadline if waiting else None,
            override_until=until,
            boost_until=boost_until,
        )
    elif state.boost is not None:
        desired = Desired(
            "heat",
            state.boost.temperature,
            Mode.BOOST,
            target,
            override_until=until,
            boost_until=boost_until,
        )
    elif override is not None and override.temperature is None:
        desired = Desired("off", None, Mode.OFF, target, override_until=until)
    elif override is not None and override.temperature is not None:
        mode = Mode.TIMED if until is not None else Mode.MANUAL
        desired = Desired("heat", override.temperature, mode, target, override_until=until)
    else:
        mode = Mode.IDLE if inputs.idle or not inputs.schedule_on else Mode.SCHEDULE
        desired = Desired("heat", target, mode, target)
    return _frost(state, desired, inputs, config)


def _frost(state: RoomState, desired: Desired, inputs: Inputs, config: RoomConfig) -> Desired:
    frost = config.frost_temperature
    if desired.hvac_mode == "heat":
        state.frost_active = False
        if desired.temperature is not None and desired.temperature < frost:
            return replace(desired, temperature=round_to_step(frost))
        return desired
    room = inputs.room_temperature
    if room is not None and (
        room < frost or (state.frost_active and room < frost + FROST_HYSTERESIS)
    ):
        state.frost_active = True
        return replace(desired, hvac_mode="heat", temperature=round_to_step(frost), mode=Mode.FROST)
    state.frost_active = False
    return desired


def _next_wakeup(state: RoomState, config: RoomConfig, now: datetime) -> datetime | None:
    times = [state.window_deadline]
    if (due := _reminder_due(state, config)) is not None and due > now:
        times.append(due)
    if state.override is not None and isinstance(state.override.expires, datetime):
        times.append(state.override.expires)
    if state.boost is not None:
        times.append(state.boost.until)
    present = [t for t in times if t is not None]
    return min(present) if present else None
