"""Tell our own writes to a thermostat apart from changes made by someone else.

A write reaches Home Assistant as one or two state reports (mode, then setpoint). Reports within
5 s of our service call carry its context id; later ones are matched by value. The Matter server
may also deliver a write minutes late, after a newer one: a report of a value we commanded
recently is ours, just stale. A thermostat that comes back after a drop-out with a value that is
neither what it had before nor something we commanded was changed by someone while it was away.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

SETTLE = timedelta(seconds=30)
TOLERANCE = 0.05

type Setting = tuple[str | None, float | None]  # (hvac mode, setpoint)


@dataclass(frozen=True, slots=True)
class TrvView:
    """A thermostat as its state shows it."""

    available: bool
    hvac_mode: str | None = None
    setpoint: float | None = None


@dataclass(slots=True)
class Command:
    """Our current write to a thermostat: before → wanted, and the contexts it was sent with."""

    prev: Setting
    want: tuple[str, float | None]
    issued_at: datetime
    context_ids: set[str] = field(default_factory=set)
    returned_at: datetime | None = None
    confirmed: bool = False  # the thermostat reported the wanted value


class Report(StrEnum):
    """What a state report of a thermostat means."""

    IGNORED = "ignored"  # nothing relevant changed, or nothing to compare with yet
    OURS = "ours"  # carries our context
    CONVERGED = "converged"  # whoever did it, the thermostat now is where we want it
    INTERMEDIATE = "intermediate"  # a step on the way from prev to want, shortly after our write
    STALE = "stale"  # a value we commanded earlier, delivered late: ours, but outdated
    RECONNECTED = "reconnected"  # back after a drop-out, unchanged by anyone
    EXTERNAL = "external"  # someone else changed it


def matches(view: TrvView, setting: Setting) -> bool:
    """Return whether the thermostat shows `setting` (an off thermostat's setpoint is moot)."""
    if view.hvac_mode != setting[0]:
        return False
    return view.hvac_mode == "off" or _same(view.setpoint, setting[1])


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
    known: Setting | None = None,
    recent: Iterable[Setting] = (),
) -> Report:
    """Classify one state report of a thermostat.

    `known` is what the thermostat last settled on before this report; `recent` are values we
    commanded lately other than `desired`.
    """
    if not new.available or old is None:
        return Report.IGNORED
    if not old.available:
        return _reconnected(new, desired, known, list(recent))
    mode_changed = new.hvac_mode != old.hvac_mode
    setpoint_changed = not _same(new.setpoint, old.setpoint)
    if not mode_changed and not setpoint_changed:
        return Report.IGNORED
    if not mode_changed and new.hvac_mode == "off":
        return Report.IGNORED  # the setpoint of a thermostat that is off does not matter
    if command is not None and context_id is not None and context_id in command.context_ids:
        return Report.OURS
    # Before "on the way": the last report of our write may come after its context expired.
    if matches(new, desired):
        return Report.CONVERGED
    if command is not None and not command.confirmed and _on_the_way(new, command, now):
        return Report.INTERMEDIATE
    if any(matches(new, r) for r in recent):
        return Report.STALE
    return Report.EXTERNAL


def _reconnected(
    new: TrvView, desired: Setting, known: Setting | None, recent: list[Setting]
) -> Report:
    if matches(new, desired):
        return Report.CONVERGED
    if known is None or matches(new, known) or any(matches(new, r) for r in recent):
        return Report.RECONNECTED
    return Report.EXTERNAL  # turned while Home Assistant could not see it


def _on_the_way(new: TrvView, command: Command, now: datetime) -> bool:
    since = command.returned_at or command.issued_at
    if now - since > SETTLE:
        return False
    modes = {command.prev[0], command.want[0]}
    setpoints = (command.prev[1], command.want[1])
    return new.hvac_mode in modes and any(_same(new.setpoint, s) for s in setpoints)
