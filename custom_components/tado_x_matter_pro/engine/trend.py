"""The temperature trend in °C/h, computed exactly like Home Assistant's derivative sensor.

Settings as in a derivative helper with time window 10 min, max sub-interval 5 min, unit per hour,
2 decimals. Each state change adds a segment (old report → new update, slope); the trend is the
time-weighted sum of the segments inside the window. Reports of an unchanged value add flat
segments; without any report the trend is recalculated every max sub-interval until it is zero.

Tado X reports its reading every minute while it changes, at 0.01 °C and practically without noise,
so 10 minutes are enough: replaying recorded history (tests/python/replay.py), a 20-minute window
kept "heating" about 11 minutes past the reading's peak, 10 minutes about 5, and 5 minutes turned
bumps of a few hundredths into short false "heating".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

WINDOW = timedelta(minutes=10)
MAX_SUB_INTERVAL = timedelta(minutes=5)
DIGITS = 2


@dataclass(slots=True)
class Trend:
    """The trend of one temperature sensor."""

    window: timedelta = WINDOW
    max_sub_interval: timedelta = MAX_SUB_INTERVAL
    value: float | None = None
    segments: list[tuple[datetime, datetime, float]] = field(default_factory=list)
    last_valid: tuple[float, datetime] | None = None

    def changed(
        self,
        old_value: float | None,
        old_reported: datetime,
        new_value: float | None,
        new_updated: datetime,
    ) -> datetime | None:
        """Add a state change of the sensor; return when to recalculate without news."""
        if new_value is None:
            return None
        self._add(old_value, old_reported, new_value, new_updated)
        return new_updated + self.max_sub_interval

    def reported(
        self, value: float | None, old_reported: datetime, reported: datetime
    ) -> datetime | None:
        """Add a report of the unchanged value; return when to recalculate."""
        if value is None or self.value == 0:
            return None  # a zero trend of an unchanged sensor stays zero
        self._add(value, old_reported, value, reported)
        return reported + self.max_sub_interval

    def tick(self, now: datetime) -> datetime | None:
        """Recalculate after the max sub-interval without news; return the next time."""
        self._prune(now)
        raw = self._weighted(now)
        self.value = round(raw, DIGITS) + 0.0  # + 0.0 turns -0.0 into 0.0
        return now + self.max_sub_interval if raw != 0 else None

    def _add(
        self, old_value: float | None, old_time: datetime, new_value: float, new_time: datetime
    ) -> None:
        if old_value is None:
            if self.last_valid is None:
                return  # valid for the first time: nothing to compare with yet
            old_value, old_time = self.last_valid
        self._prune(new_time)
        elapsed = (new_time - old_time).total_seconds()
        if elapsed <= 0:
            return
        slope = (new_value - old_value) / elapsed * 3600
        self.segments.append((old_time, new_time, slope))
        self.last_valid = (new_value, new_time)
        raw = slope if elapsed > self.window.total_seconds() else self._weighted(new_time)
        self.value = round(raw, DIGITS) + 0.0

    def _prune(self, now: datetime) -> None:
        window = self.window.total_seconds()
        self.segments = [s for s in self.segments if (now - s[1]).total_seconds() < window]

    def _weighted(self, now: datetime) -> float:
        window = self.window.total_seconds()
        start_of_window = now - self.window
        return sum(
            slope * (end - max(start, start_of_window)).total_seconds() / window
            for start, end, slope in self.segments
        )
