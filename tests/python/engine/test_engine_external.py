"""Tests for telling our own thermostat writes from changes made by someone else."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.tado_x_matter_pro.engine.external import (
    Command,
    Report,
    TrvView,
    classify,
)

T0 = datetime(2026, 10, 27, 16, 0, tzinfo=UTC)
HEAT_18 = TrvView(available=True, hvac_mode="heat", setpoint=18.0)
HEAT_21 = TrvView(available=True, hvac_mode="heat", setpoint=21.0)
OFF_18 = TrvView(available=True, hvac_mode="off", setpoint=18.0)
COMMAND = Command(prev=("heat", 18.0), want=("heat", 21.0), issued_at=T0, context_ids={"ours"})
# Switching on: Matter reports the mode first, the setpoint second.
SWITCH_ON = Command(prev=("off", 18.0), want=("heat", 21.0), issued_at=T0, context_ids={"ours"})


@pytest.mark.parametrize(
    ("old", "new", "desired", "command", "context", "seconds", "expected"),
    [
        (HEAT_18, HEAT_21, ("heat", 21.0), COMMAND, "ours", 2, Report.OURS),
        # our value, reported after the context expired: arrived, not "on the way"
        (HEAT_18, HEAT_21, ("heat", 21.0), COMMAND, "late", 8, Report.CONVERGED),
        (OFF_18, HEAT_18, ("heat", 21.0), SWITCH_ON, "late", 8, Report.INTERMEDIATE),
        (HEAT_18, HEAT_21, ("heat", 21.0), COMMAND, "late", 120, Report.CONVERGED),
        (HEAT_18, HEAT_21, ("heat", 18.0), None, "dial", 0, Report.EXTERNAL),
        (HEAT_21, OFF_18, ("heat", 21.0), None, "dial", 0, Report.EXTERNAL),
        (HEAT_18, HEAT_18, ("heat", 18.0), None, None, 0, Report.IGNORED),
        (OFF_18, TrvView(True, "off", 22.0), ("off", None), None, "app", 0, Report.IGNORED),
        # back from a drop-out, nothing to compare with: re-apply
        (TrvView(False), HEAT_21, ("heat", 18.0), None, "x", 0, Report.RECONNECTED),
        (HEAT_18, TrvView(False), ("heat", 18.0), None, "x", 0, Report.IGNORED),
        (None, HEAT_21, ("heat", 18.0), None, "x", 0, Report.IGNORED),
        (OFF_18, HEAT_18, ("off", None), None, "dial", 0, Report.EXTERNAL),
        (HEAT_21, OFF_18, ("off", None), None, "x", 0, Report.CONVERGED),
    ],
)
def test_classify(
    old: TrvView | None,
    new: TrvView,
    desired: tuple[str, float | None],
    command: Command | None,
    context: str | None,
    seconds: int,
    expected: Report,
) -> None:
    now = T0 + timedelta(seconds=seconds)
    assert (
        classify(old, new, desired=desired, command=command, context_id=context, now=now)
        is expected
    )


def test_dial_shortly_after_our_write_to_another_value_is_external() -> None:
    new = TrvView(True, "heat", 23.0)
    report = classify(
        HEAT_21, new, desired=("heat", 21.0), command=COMMAND, context_id="dial", now=T0
    )
    assert report is Report.EXTERNAL


def reconnect(
    new: TrvView, known: tuple[str, float] | None, recent: list[tuple[str, float]]
) -> Report:
    return classify(
        TrvView(False),
        new,
        desired=("heat", 21.0),
        command=None,
        context_id=None,
        now=T0,
        known=known,
        recent=recent,
    )


def test_back_from_a_drop_out() -> None:
    assert reconnect(HEAT_21, ("heat", 18.0), []) is Report.CONVERGED  # already right
    assert reconnect(HEAT_18, ("heat", 18.0), []) is Report.RECONNECTED  # as it was: re-apply
    assert reconnect(HEAT_18, ("heat", 20.0), [("heat", 18.0)]) is Report.RECONNECTED  # ours
    # neither what it had nor anything we sent: turned while Home Assistant could not see it
    assert reconnect(TrvView(True, "heat", 24.0), ("heat", 18.0), []) is Report.EXTERNAL


def test_a_late_delivery_of_an_older_write_is_stale() -> None:
    late = classify(
        HEAT_21,
        HEAT_18,
        desired=("heat", 21.0),
        command=COMMAND,
        context_id=None,
        now=T0 + timedelta(minutes=5),
        recent=[("heat", 18.0)],
    )
    assert late is Report.STALE


def test_turning_back_to_the_old_value_after_our_write_arrived_is_a_change() -> None:
    confirmed = Command(
        prev=("heat", 18.0), want=("heat", 21.0), issued_at=T0, context_ids={"ours"}, confirmed=True
    )
    report = classify(
        HEAT_21, HEAT_18, desired=("heat", 21.0), command=confirmed, context_id="dial", now=T0
    )
    assert report is Report.EXTERNAL
