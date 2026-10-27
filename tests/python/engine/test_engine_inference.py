"""Tests for the heating status rule (ported from the tuned Jinja macro)."""

from __future__ import annotations

import pytest

from custom_components.tado_x_matter_pro.engine.inference import Status, infer, room_status

H, R, OFF = Status.HEATING, Status.REACHED, Status.OFF


@pytest.mark.parametrize(
    ("mode", "setpoint", "reading", "trend", "previous", "expected"),
    [
        ("off", 21.0, 18.0, 2.0, H, OFF),
        ("heat", None, 18.0, 0.0, None, OFF),
        # not heating before: start when below/at the setpoint and not cooling …
        ("heat", 21.0, 20.0, 0.0, None, H),
        ("heat", 21.0, 21.0, 0.0, R, H),
        ("heat", 21.0, 20.0, -0.3, R, R),
        # … or when clearly warming even a bit above
        ("heat", 21.0, 22.0, 0.8, R, H),
        ("heat", 21.0, 22.5, 0.9, R, R),
        ("heat", 21.0, 21.5, 0.5, R, R),
        # heating before: stop when cooling …
        ("heat", 21.0, 20.0, -0.5, H, R),
        # … when clearly above and no longer rising …
        ("heat", 21.0, 21.4, 0.1, H, R),
        ("heat", 21.0, 21.4, 0.2, H, H),
        # … or far above (after a setback) without strong rise
        ("heat", 18.0, 19.0, 0.7, H, R),
        ("heat", 18.0, 19.0, 0.8, H, H),
        # a float edge: 22 − 22.2 rounds to −0.2, not −0.1999
        ("heat", 22.0, 22.2, 0.0, None, R),
        # unknown trend counts as flat
        ("heat", 21.0, 20.5, None, None, H),
    ],
)
def test_infer(
    mode: str,
    setpoint: float | None,
    reading: float,
    trend: float | None,
    previous: Status | None,
    expected: Status,
) -> None:
    assert infer(mode, setpoint, reading, trend, previous) is expected


def test_room_status_is_the_most_active() -> None:
    assert room_status([]) is OFF
    assert room_status([OFF, R]) is R
    assert room_status([R, H, OFF]) is H
