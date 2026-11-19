"""Which changes of a room end up in the logbook."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.tado_x_matter_pro.engine.log import Entry, Kind, entries
from custom_components.tado_x_matter_pro.engine.model import (
    Boost,
    Expiry,
    Override,
    RoomState,
    WindowPhase,
)

T1 = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
HOLD = Override(23.0)


def log(before: RoomState, after: RoomState, *, resumed: bool = False) -> list[Entry]:
    return entries(before, after, resumed=resumed)


def test_holds_overrides_and_their_end() -> None:
    assert log(RoomState(), RoomState(override=HOLD)) == [Entry(Kind.HOLD, 23.0)]
    assert log(RoomState(), RoomState(override=Override(18.0, T1))) == [Entry(Kind.TIMED, 18.0, T1)]
    assert log(RoomState(), RoomState(override=Override(None, Expiry.NEVER))) == [
        Entry(Kind.ROOM_OFF)
    ]
    assert log(RoomState(override=HOLD), RoomState()) == [Entry(Kind.HOLD_ENDED)]
    assert log(RoomState(override=HOLD), RoomState(override=HOLD)) == []


def test_the_window_acknowledgement_alone_is_no_news() -> None:
    acked = Override(23.0, window_ack=True)
    assert log(RoomState(override=acked), RoomState(override=HOLD)) == []


def test_resume_is_one_entry_if_it_changed_something() -> None:
    assert log(RoomState(override=HOLD), RoomState(), resumed=True) == [Entry(Kind.RESUMED)]
    assert log(RoomState(), RoomState(), resumed=True) == []


def test_windows_switch_off_and_back_on() -> None:
    opening = RoomState(window=WindowPhase.OPENING)
    assert log(opening, RoomState(window=WindowPhase.OPEN)) == [Entry(Kind.WINDOW_OFF)]
    waiting = RoomState(window=WindowPhase.WAITING)
    assert log(waiting, RoomState(window=WindowPhase.OPEN)) == []  # reopened during the wait
    assert log(waiting, RoomState()) == [Entry(Kind.WINDOW_ON)]
    assert log(opening, RoomState()) == []  # a short opening


def test_boost_and_its_end() -> None:
    boost = Boost(30.0, T1)
    assert log(RoomState(), RoomState(boost=boost)) == [Entry(Kind.BOOST, 30.0, T1)]
    assert log(RoomState(boost=boost), RoomState()) == [Entry(Kind.BOOST_ENDED)]


def test_the_window_reminder() -> None:
    open_ = RoomState(window=WindowPhase.OPEN)
    reminded = RoomState(window=WindowPhase.OPEN, reminded=True)
    assert log(open_, reminded) == [Entry(Kind.WINDOW_REMINDER)]
    assert log(reminded, reminded) == []
