"""Tests for the trend (a port of Home Assistant's derivative sensor)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.tado_x_matter_pro.engine.trend import Trend

T0 = datetime(2026, 10, 27, 16, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_steady_rise_over_the_whole_window() -> None:
    trend = Trend()
    value = 20.0
    for minute in range(0, 21, 2):
        trend.changed(value, at(minute), value + 0.1, at(minute + 2))
        value += 0.1
    assert trend.value == 3.0  # 0.1 °C per 2 min


def test_a_single_step_is_weighted_by_the_window() -> None:
    trend = Trend()
    trend.changed(20.0, at(0), 20.5, at(10))  # 3 °C/h over half the window
    assert trend.value == 1.5


def test_a_gap_longer_than_the_window_reports_the_plain_slope() -> None:
    trend = Trend()
    trend.changed(20.0, at(0), 21.0, at(30))
    assert trend.value == 2.0


def test_reports_of_an_unchanged_value_flatten_the_trend() -> None:
    trend = Trend()
    trend.changed(20.0, at(0), 20.5, at(10))
    assert trend.reported(20.5, at(10), at(20)) == at(25)
    assert trend.value == 1.5  # the step is still fully inside the window
    trend.reported(20.5, at(20), at(30))
    assert trend.value == 0.0
    assert trend.reported(20.5, at(30), at(40)) is None  # zero stays zero


def test_tick_decays_the_trend_until_zero() -> None:
    trend = Trend()
    trend.changed(20.0, at(0), 20.5, at(10))
    assert trend.tick(at(20)) == at(25)
    assert trend.value == 1.5
    assert trend.tick(at(31)) is None
    assert trend.value == 0.0


def test_first_valid_value_has_nothing_to_compare_with() -> None:
    trend = Trend()
    trend.changed(None, at(0), 20.0, at(1))
    assert trend.value is None
    trend.changed(20.0, at(1), 20.2, at(5))
    assert trend.value is not None


def test_recovering_from_an_invalid_value_uses_the_last_valid_one() -> None:
    trend = Trend()
    trend.changed(20.0, at(0), 20.4, at(4))
    trend.changed(None, at(8), 20.8, at(8))
    assert trend.last_valid == (20.8, at(8))
    start, end, slope = trend.segments[-1]
    assert (start, end, round(slope, 6)) == (at(4), at(8), 6.0)
