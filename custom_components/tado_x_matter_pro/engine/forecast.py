"""When the room's target changes next by itself, and to what – for "21° → 18° at 23:00".

The room is stepped through every moment something could change without anyone acting: block
edges of the schedule, the end of the wait after a window, the end of a timed override or a boost.
The first moment its target differs is the answer. So a block continuing past midnight is no
change, a hold ends at the next plan change, a boost falls back to what lies underneath, and
while away the schedule's edges change nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .model import Desired, Inputs, RoomConfig, RoomState
from .room import step

HORIZON = timedelta(days=8)


@dataclass(frozen=True, slots=True)
class Block:
    """One block of the schedule, in UTC; `temperature` from its additional data, if any."""

    start: datetime
    end: datetime
    temperature: float | None = None


@dataclass(frozen=True, slots=True)
class Forecast:
    """The next change: when, and the target then (None: the thermostats go off)."""

    at: datetime
    temperature: float | None


def _at(inputs: Inputs, blocks: list[Block], when: datetime) -> Inputs:
    if not blocks:
        return inputs  # the schedule's blocks are not known: only deadlines can change things
    block = next((b for b in blocks if b.start <= when < b.end), None)
    return replace(
        inputs,
        schedule_on=block is not None,
        block_temperature=block.temperature if block else None,
    )


def forecast(  # noqa: PLR0913 – the room's whole picture
    state: RoomState,
    inputs: Inputs,
    config: RoomConfig,
    now: datetime,
    *,
    desired: Desired,
    blocks: list[Block],
) -> Forecast | None:
    """Return the next change of the room's target, or None within the horizon."""
    horizon = now + HORIZON
    moments = {b.start for b in blocks} | {b.end for b in blocks}
    moments |= {state.window_deadline} if state.window_deadline else set()
    if state.override is not None and isinstance(state.override.expires, datetime):
        moments.add(state.override.expires)
    if state.boost is not None:
        moments.add(state.boost.until)
    current = (desired.hvac_mode, desired.temperature)
    for when in sorted(m for m in moments if now < m <= horizon):
        result = step(state, _at(inputs, blocks, when), config, when)
        target = (result.desired.hvac_mode, result.desired.temperature)
        if target != current:
            heating = result.desired.hvac_mode == "heat"
            return Forecast(when, result.desired.temperature if heating else None)
        state = result.state
    return None
