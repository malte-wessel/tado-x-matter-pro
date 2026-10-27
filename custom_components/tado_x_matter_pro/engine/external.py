"""Tell our own writes to a thermostat apart from changes made by someone else.

A write reaches Home Assistant as one or two state reports (mode, then setpoint). Reports within
5 s of our service call carry its context id; later ones are matched by value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

SETTLE = timedelta(seconds=30)
TOLERANCE = 0.05


@dataclass(frozen=True, slots=True)
class TrvView:
    """A thermostat as its state shows it."""

    available: bool
    hvac_mode: str | None = None
    setpoint: float | None = None


@dataclass(slots=True)
class Command:
    """Our last write to a thermostat: before → wanted, and the contexts it was sent with."""

    prev: tuple[str | None, float | None]
    want: tuple[str, float | None]
    issued_at: datetime
    context_ids: set[str] = field(default_factory=set)
    returned_at: datetime | None = None


class Report(StrEnum):
    """What a state report of a thermostat means."""

    IGNORED = "ignored"  # nothing relevant changed, or the thermostat is (re)connecting
    OURS = "ours"  # carries our context
    INTERMEDIATE = "intermediate"  # a step on the way from prev to want, shortly after our write
    CONVERGED = "converged"  # whoever did it, the thermostat now is where we want it
    EXTERNAL = "external"  # someone else changed it


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= TOLERANCE


def classify(  # noqa: PLR0911, PLR0913 – one return per rule reads best here
    old: TrvView | None,
    new: TrvView,
    *,
    desired: tuple[str, float | None],
    command: Command | None,
    context_id: str | None,
    now: datetime,
) -> Report:
    """Classify one state report of a thermostat."""
    if not new.available or old is None or not old.available:
        return Report.IGNORED
    mode_changed = new.hvac_mode != old.hvac_mode
    setpoint_changed = not _same(new.setpoint, old.setpoint)
    if not mode_changed and not setpoint_changed:
        return Report.IGNORED
    if not mode_changed and new.hvac_mode == "off":
        return Report.IGNORED  # the setpoint of a thermostat that is off does not matter
    if command is not None and context_id is not None and context_id in command.context_ids:
        return Report.OURS
    if command is not None and _on_the_way(new, command, now):
        return Report.INTERMEDIATE
    if new.hvac_mode == desired[0] and (desired[0] == "off" or _same(new.setpoint, desired[1])):
        return Report.CONVERGED
    return Report.EXTERNAL


def _on_the_way(new: TrvView, command: Command, now: datetime) -> bool:
    since = command.returned_at or command.issued_at
    if now - since > SETTLE:
        return False
    modes = {command.prev[0], command.want[0]}
    setpoints = (command.prev[1], command.want[1])
    return new.hvac_mode in modes and any(_same(new.setpoint, s) for s in setpoints)
