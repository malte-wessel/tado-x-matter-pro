"""Is a thermostat heating? Tado X over Matter does not say, so read it from the temperatures.

The thermostat sits at the radiator: while its valve is open, its own reading rises quickly and
usually stays above the setpoint. The rule uses d = setpoint − reading (0.1 °C) and the reading's
trend t (°C/h), with hysteresis through the previous status:

- previously heating → reached when t ≤ −0.5 (cooling, valve closed),
  or d ≤ −0.4 and t < 0.2 (clearly above the setpoint, no longer rising),
  or d ≤ −1.0 and t < 0.8 (far above, e.g. after a setback); otherwise still heating;
- otherwise → heating when d > −0.1 and t > −0.3 (below or at the setpoint, not cooling),
  or t ≥ 0.8 and d > −1.5 (radiator clearly warm, also when overshooting); otherwise reached.

Tuned on three days of real data from Tado X thermostats; tests/python/replay.py replays anonymized
recordings through it. It reports heat arriving at the radiator: after the setpoint goes up it says
heating once the reading turns upwards, not when the valve is asked to open.
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """A thermostat's heating status; ordered off < reached < heating."""

    OFF = "off"
    REACHED = "reached"
    HEATING = "heating"


RANK = {Status.OFF: 0, Status.REACHED: 1, Status.HEATING: 2}


def infer(
    hvac_mode: str | None,
    setpoint: float | None,
    reading: float | None,
    trend: float | None,
    previous: Status | None,
) -> Status:
    """Infer one thermostat's status."""
    if hvac_mode != "heat" or setpoint is None or reading is None:
        return Status.OFF
    d = round(setpoint - reading, 1)
    t = trend or 0.0
    if previous is Status.HEATING:
        stopped = t <= -0.5 or (d <= -0.4 and t < 0.2) or (d <= -1.0 and t < 0.8)
        return Status.REACHED if stopped else Status.HEATING
    started = (d > -0.1 and t > -0.3) or (t >= 0.8 and d > -1.5)
    return Status.HEATING if started else Status.REACHED


def room_status(statuses: list[Status]) -> Status:
    """Return the room's status: the most active of its thermostats."""
    return max(statuses, key=RANK.__getitem__, default=Status.OFF)
