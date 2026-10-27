"""The heating status on recorded Tado X history (anonymized fixtures in tests/fixtures/replay)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from custom_components.tado_x_matter_pro.engine.inference import Status
from tests.python.replay import Sample, end_lags, fixture_names, heating_hours, load, replay

# A shorter "heating" that did not end by switching off would be a blip, not a radiator heating.
MIN_HEATING_SECONDS = 600
# Shorter ones come from a write reported as two states (mode, then setpoint), not from the trend.
TWO_STEP_WRITE_SECONDS = 60


def heating_periods(samples: list[Sample]) -> list[tuple[int, int, str]]:
    """Return (start, end, mode at the end) of every period in `heating`."""
    periods: list[tuple[int, int, str]] = []
    start: int | None = None
    for a, b in pairwise(samples):
        if a.status is not Status.HEATING and b.status is Status.HEATING:
            start = b.at
        elif a.status is Status.HEATING and b.status is not Status.HEATING and start is not None:
            periods.append((start, b.at, b.hvac_mode))
            start = None
    return periods


@pytest.mark.parametrize("name", fixture_names())
def test_a_thermostat_that_is_off_is_off(name: str) -> None:
    samples = replay(load(name))
    assert all(s.status is Status.OFF for s in samples if s.hvac_mode != "heat")


@pytest.mark.parametrize("name", fixture_names())
def test_no_short_blips_of_heating(name: str) -> None:
    blips = [
        (start, end)
        for start, end, mode in heating_periods(replay(load(name)))
        if mode == "heat" and TWO_STEP_WRITE_SECONDS < end - start < MIN_HEATING_SECONDS
    ]
    assert blips == []


def test_heating_starts_soon_after_the_reading_turns_upwards() -> None:
    # After the setpoint goes up the reading may keep falling for a while (the radiator is still
    # cold); the status follows the heat, not the request: heating once the reading turns.
    fixture = load("strong")
    samples = replay(fixture)
    raised = [
        at
        for (_, _, before), (at, mode, after) in pairwise(fixture.thermostat)
        if mode == "heat" and before is not None and after is not None and after > before
    ]
    assert raised
    for at in raised:
        after = [(t, v) for t, v in fixture.readings if at <= t <= at + 1800 and v is not None]
        turned = min(after, key=lambda reading: (reading[1], -reading[0]))[0]
        heating = next(s.at for s in samples if s.at >= at and s.status is Status.HEATING)
        assert heating - turned <= 6 * 60, at


def test_heating_ends_soon_after_the_radiator_peaks() -> None:
    fixture = load("strong")
    lags = end_lags(replay(fixture), fixture)
    assert len(lags) == 5
    assert all(0 <= lag <= 8 for lag in lags), lags  # minutes after the peak


def test_a_setpoint_just_above_the_reading_counts_as_heating_for_the_whole_block() -> None:
    # The reading barely rises, but it stays below the setpoint: Tado X keeps its valve (partly)
    # open, so the status says heating until the block ends.
    fixture = load("weak_demand")
    (_, _, idle), (start, _, block), (end, _, _) = fixture.thermostat[:3]
    assert idle is not None
    assert block is not None
    assert block - idle <= 3
    inside = [s for s in replay(fixture) if start < s.at < end]
    assert inside
    assert all(s.status is Status.HEATING for s in inside)


def test_a_radiator_that_never_opens_never_shows_heating() -> None:
    assert heating_hours(replay(load("no_demand"))) == 0
