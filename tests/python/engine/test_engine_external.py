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


@pytest.mark.parametrize(
    ("old", "new", "desired", "command", "context", "seconds", "expected"),
    [
        (HEAT_18, HEAT_21, ("heat", 21.0), COMMAND, "ours", 2, Report.OURS),
        (HEAT_18, HEAT_21, ("heat", 21.0), COMMAND, "late", 8, Report.INTERMEDIATE),
        (HEAT_18, HEAT_21, ("heat", 21.0), COMMAND, "late", 120, Report.CONVERGED),
        (HEAT_18, HEAT_21, ("heat", 18.0), None, "dial", 0, Report.EXTERNAL),
        (HEAT_21, OFF_18, ("heat", 21.0), None, "dial", 0, Report.EXTERNAL),
        (HEAT_18, HEAT_18, ("heat", 18.0), None, None, 0, Report.IGNORED),
        (OFF_18, TrvView(True, "off", 22.0), ("off", None), None, "app", 0, Report.IGNORED),
        (TrvView(False), HEAT_21, ("heat", 18.0), None, "x", 0, Report.IGNORED),
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
