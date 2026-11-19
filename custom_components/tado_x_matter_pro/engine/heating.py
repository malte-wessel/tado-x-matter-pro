"""Is a thermostat heating? Taken from a demand entity, since Tado X over Matter does not say.

Over Matter a Tado X reports its mode, setpoint and reading, but neither its valve position nor its
heating demand. Whoever wants a heating status configures a demand per thermostat: a percentage
(e.g. a cloud integration's heating power) or an on/off value (e.g. a threshold on a pipe sensor).
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """A thermostat's heating status."""

    OFF = "off"
    REACHED = "reached"
    HEATING = "heating"


def status(
    hvac_mode: str | None, *, demand: float | bool | None, threshold: float
) -> Status | None:
    """Return the thermostat's status; None when it is not known.

    A thermostat that is off is off, whatever its demand says (the demand may lag behind).
    """
    if hvac_mode == "off":
        return Status.OFF
    if hvac_mode != "heat" or demand is None:
        return None
    if isinstance(demand, bool):
        return Status.HEATING if demand else Status.REACHED
    return Status.HEATING if demand >= threshold else Status.REACHED


def room_action(statuses: list[Status | None]) -> Status | None:
    """Return the room's status: off if all are off, heating if any heats, reached if all known."""
    if not statuses:
        return None
    if all(s is Status.OFF for s in statuses):
        return Status.OFF
    if Status.HEATING in statuses:
        return Status.HEATING
    if None in statuses:
        return None
    return Status.REACHED
