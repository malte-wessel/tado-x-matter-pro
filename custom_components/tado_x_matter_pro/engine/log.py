"""What a step changed that belongs in the logbook: holds, overrides, resume, windows, boost."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .model import Override, RoomState, WindowPhase


class Kind(StrEnum):
    """A logbook entry's kind; messages.py has its text."""

    HOLD = "hold"  # a temperature held until the next plan change
    TIMED = "timed"  # a temperature until a time
    ROOM_OFF = "room_off"
    HOLD_ENDED = "hold_ended"  # the plan applies again: a plan change or the end time
    RESUMED = "resumed"
    WINDOW_OFF = "window_off"
    WINDOW_ON = "window_on"
    BOOST = "boost"
    BOOST_ENDED = "boost_ended"
    WINDOW_REMINDER = "window_reminder"  # open too long: also a notification


@dataclass(frozen=True, slots=True)
class Entry:
    """One logbook entry of a room."""

    kind: Kind
    temperature: float | None = None
    until: datetime | None = None


def _key(override: Override | None) -> tuple[object, ...] | None:
    # What the user set; the window acknowledgement alone is no news.
    if override is None:
        return None
    return (override.temperature, override.expires, override.preset)


def entries(before: RoomState, after: RoomState, *, resumed: bool) -> list[Entry]:
    """Return the entries for going from `before` to `after`; `resumed` if resume caused it."""
    found: list[Entry] = []
    changed = _key(before.override) != _key(after.override) or before.boost != after.boost
    if resumed:
        if changed or before.window is WindowPhase.WAITING:
            found.append(Entry(Kind.RESUMED))
    else:
        found.extend(_boost(before, after))
        if _key(before.override) != _key(after.override):
            found.extend(_override(before.override, after.override))
    found.extend(_window(before, after))
    if after.reminded and not before.reminded:
        found.append(Entry(Kind.WINDOW_REMINDER))
    return found


def _boost(before: RoomState, after: RoomState) -> list[Entry]:
    if after.boost is not None and after.boost != before.boost:
        return [Entry(Kind.BOOST, after.boost.temperature, after.boost.until)]
    if before.boost is not None and after.boost is None:
        return [Entry(Kind.BOOST_ENDED)]
    return []


def _override(before: Override | None, after: Override | None) -> list[Entry]:
    if after is None:
        return [Entry(Kind.HOLD_ENDED)] if before is not None else []
    if after.temperature is None:
        return [Entry(Kind.ROOM_OFF)]
    if isinstance(after.expires, datetime):
        return [Entry(Kind.TIMED, after.temperature, after.expires)]
    return [Entry(Kind.HOLD, after.temperature)]


def _window(before: RoomState, after: RoomState) -> list[Entry]:
    # Only news if the window is what switches the room: not for a room that is off anyway, nor
    # for one that heats despite the window (a temperature set while it was open).
    if after.override is not None and after.override.temperature is None:
        return []
    paused = (WindowPhase.OPEN, WindowPhase.WAITING)
    if after.window is WindowPhase.OPEN and before.window not in paused and not _ack(after):
        return [Entry(Kind.WINDOW_OFF)]
    if after.window is WindowPhase.CLOSED and before.window in paused and not _ack(before):
        return [Entry(Kind.WINDOW_ON)]
    return []


def _ack(state: RoomState) -> bool:
    return state.override is not None and state.override.window_ack
