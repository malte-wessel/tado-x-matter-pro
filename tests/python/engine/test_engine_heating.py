"""Tests for the heating status taken from a demand entity."""

from __future__ import annotations

import pytest

from custom_components.tado_x_matter_pro.engine.heating import Status, room_action, status

H, R, OFF = Status.HEATING, Status.REACHED, Status.OFF


@pytest.mark.parametrize(
    ("mode", "demand", "expected"),
    [
        ("heat", 3.0, H),  # from the threshold on
        ("heat", 2.9, R),
        ("heat", 0.0, R),
        ("heat", 100.0, H),
        ("heat", True, H),  # an on/off demand
        ("heat", False, R),
        ("heat", None, None),  # demand unknown
        ("off", 80.0, OFF),  # off wins: a cloud demand can lag behind
        ("off", None, OFF),
        (None, 80.0, None),  # thermostat unavailable
    ],
)
def test_status(
    mode: str | None,
    demand: float | bool | None,  # noqa: FBT001 – a parametrized demand, on/off included
    expected: Status | None,
) -> None:
    assert status(mode, demand=demand, threshold=3.0) is expected


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], None),
        ([OFF, OFF], OFF),
        ([OFF, H], H),
        ([R, H], H),
        ([R, None], None),  # one might heat, unknown
        ([H, None], H),  # one heats for sure
        ([R, R], R),
        ([OFF, R], R),
        ([OFF, None], None),
    ],
)
def test_room_action(statuses: list[Status | None], expected: Status | None) -> None:
    assert room_action(statuses) is expected
