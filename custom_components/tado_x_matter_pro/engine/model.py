"""The room's data: configuration, inputs, persisted state and the desired output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

TEMPERATURE_STEP = 0.5


class WindowPhase(StrEnum):
    """Where the room is in the window cycle."""

    CLOSED = "closed"
    OPENING = "opening"  # a window is open, the open delay runs
    OPEN = "open"  # thermostats are off
    WAITING = "waiting"  # all windows closed again, the close delay runs


class Mode(StrEnum):
    """What decides the room's target right now (the Mode sensor's state)."""

    SCHEDULE = "schedule"
    IDLE = "idle"
    MANUAL = "manual"
    WINDOW = "window"
    WAITING = "waiting"
    OFF = "off"
    FROST = "frost"


class Expiry(StrEnum):
    """When an override ends, unless it carries a point in time."""

    NEXT_CHANGE = "next_change"  # the next plan change
    NEVER = "never"  # only resume ends it


@dataclass(frozen=True, slots=True)
class RoomConfig:
    """Per-room settings from the subentry and house-wide ones from the entry."""

    open_delay: timedelta = timedelta(seconds=30)
    close_delay: timedelta = timedelta(minutes=5)
    frost_temperature: float = 7.0


@dataclass(frozen=True, slots=True)
class Inputs:
    """Everything the room's decision depends on, read from Home Assistant."""

    schedule_on: bool
    block_temperature: float | None
    idle: bool
    heating_temperature: float
    idle_temperature: float
    window_open: bool
    room_temperature: float | None = None


@dataclass(slots=True)
class Override:
    """A target that wins over the plan. `temperature` None means the room is off."""

    temperature: float | None
    expires: Expiry | datetime = Expiry.NEXT_CHANGE
    # Made while a window was open: the room heats despite the window until the next opening.
    window_ack: bool = False


@dataclass(slots=True)
class RoomState:
    """What the engine remembers between steps; persisted in the store."""

    window: WindowPhase = WindowPhase.CLOSED
    window_deadline: datetime | None = None
    override: Override | None = None
    plan_key: tuple[bool, float | None, bool, float] | None = None
    frost_active: bool = False
    bounces: list[datetime] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Desired:
    """What every thermostat of the room should do, and why."""

    hvac_mode: str  # "heat" or "off"
    temperature: float | None  # the setpoint while heating
    mode: Mode
    plan_target: float
    resume_at: datetime | None = None
    override_until: datetime | None = None


def round_to_step(value: float) -> float:
    """Round a temperature to the thermostats' 0.5 °C step."""
    return round(value / TEMPERATURE_STEP) * TEMPERATURE_STEP
