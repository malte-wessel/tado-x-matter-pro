"""Replay recorded thermostat history through the trend and the heating status rule.

The fixtures in tests/fixtures/replay are anonymized recordings of Tado X thermostats: the precise
reading (0.01 °C) whenever it changed, and the thermostat's mode and setpoint, in seconds from the
start. Tado X reports its reading only when it changes, so the replay feeds the changes and the
trend's own recalculations, like monitor.py. Run it to compare trend windows:

    uv run python -m tests.python.replay
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
import json
from pathlib import Path
from statistics import median

from custom_components.tado_x_matter_pro.engine.inference import Status, infer
from custom_components.tado_x_matter_pro.engine.trend import MAX_SUB_INTERVAL, WINDOW, Trend

FIXTURES = Path(__file__).parent.parent / "fixtures" / "replay"
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
# A peak of the reading: it rose at least this much, then fell at least PEAK_DROP below its top.
PEAK_RISE = 0.5
PEAK_DROP = 0.1


@dataclass(frozen=True, slots=True)
class Fixture:
    """One recorded thermostat."""

    name: str
    readings: list[tuple[int, float | None]]
    thermostat: list[tuple[int, str, float | None]]


@dataclass(frozen=True, slots=True)
class Sample:
    """The status after one event of the replay."""

    at: int  # seconds from the start
    hvac_mode: str
    setpoint: float | None
    reading: float | None
    trend: float | None
    status: Status


def fixture_names() -> list[str]:
    """Return the names of all replay fixtures."""
    return sorted(path.stem for path in FIXTURES.glob("*.json"))


def load(name: str) -> Fixture:
    """Load a fixture by name."""
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return Fixture(
        name,
        [(at, value) for at, value in data["readings"]],
        [(at, mode, setpoint) for at, mode, setpoint in data["thermostat"]],
    )


def replay(
    fixture: Fixture,
    window: timedelta = WINDOW,
    max_sub_interval: timedelta = MAX_SUB_INTERVAL,
) -> list[Sample]:
    """Run the fixture through a trend with `window` and the rule; one sample per event."""
    trend = Trend(window=window, max_sub_interval=max_sub_interval)
    events = sorted(
        [(at, 0, mode, setpoint) for at, mode, setpoint in fixture.thermostat]
        + [(at, 1, "reading", value) for at, value in fixture.readings]
    )
    samples: list[Sample] = []
    mode, setpoint = "unavailable", None
    reading: float | None = None
    reading_at = EPOCH
    status: Status | None = None
    tick: datetime | None = None

    def evaluate(now: datetime) -> None:
        nonlocal status
        rounded = round(reading, 1) if reading is not None else None  # the climate's 0.1 °C
        status = infer(mode, setpoint, rounded, trend.value, status)
        at = int((now - EPOCH).total_seconds())
        samples.append(Sample(at, mode, setpoint, reading, trend.value, status))

    for at, kind, what, value in events:
        now = EPOCH + timedelta(seconds=at)
        while tick is not None and tick <= now:
            fired = tick
            tick = trend.tick(fired)
            evaluate(fired)
        if kind == 0:
            mode, setpoint = what, value
        else:
            # No reports of unchanged values: the old state was last reported when it changed.
            tick = trend.changed(reading, reading_at, value, now)
            reading, reading_at = value, now
        evaluate(now)
    return samples


def status_changes(samples: list[Sample]) -> int:
    """Return how often the status changed."""
    return sum(a.status != b.status for a, b in pairwise(samples))


def heating_hours(samples: list[Sample]) -> float:
    """Return the time spent in `heating`."""
    seconds = sum(b.at - a.at for a, b in pairwise(samples) if a.status is Status.HEATING)
    return seconds / 3600


def peaks(fixture: Fixture) -> list[int]:
    """Return when the reading peaked after a rise of at least PEAK_RISE."""
    found: list[int] = []
    valley: float | None = None
    top: tuple[int, float] | None = None
    for at, value in fixture.readings:
        if value is None:
            continue
        if top is not None:
            if value > top[1]:
                top = (at, value)
            elif value <= top[1] - PEAK_DROP:
                found.append(top[0])
                top, valley = None, value
            continue
        valley = value if valley is None else min(valley, value)
        if value >= valley + PEAK_RISE:
            top = (at, value)
    return found


def end_lags(samples: list[Sample], fixture: Fixture) -> list[float]:
    """Return per peak the minutes from the peak to the end of `heating` (negative: before it).

    Peaks without `heating` in the hour before them are left out.
    """
    lags: list[float] = []
    for peak in peaks(fixture):
        before = [s for s in samples if peak - 3600 <= s.at <= peak]
        if not any(s.status is Status.HEATING for s in before):
            continue
        if before[-1].status is not Status.HEATING:
            ended = next(
                b.at
                for a, b in zip(reversed(before[:-1]), reversed(before), strict=False)
                if a.status is Status.HEATING
            )
        else:
            ended = next(
                (s.at for s in samples if s.at > peak and s.status is not Status.HEATING),
                samples[-1].at,
            )
        lags.append((ended - peak) / 60)
    return lags


def main() -> None:
    """Compare trend windows on every fixture."""
    windows = [timedelta(minutes=m) for m in (20, 10, 5)]
    print(
        f"{'fixture':15} {'window':>6} {'changes':>7} {'heating h':>9} {'end lag min (per peak)':s}"
    )
    for name in fixture_names():
        fixture = load(name)
        for window in windows:
            samples = replay(fixture, window)
            lags = end_lags(samples, fixture)
            lag_text = (
                f"median {median(lags):+5.1f}  [{', '.join(f'{lag:+.0f}' for lag in lags)}]"
                if lags
                else "-"
            )
            print(
                f"{name:15} {int(window.total_seconds() // 60):>4} m "
                f"{status_changes(samples):>7} {heating_hours(samples):>9.1f} {lag_text}"
            )


if __name__ == "__main__":
    main()
