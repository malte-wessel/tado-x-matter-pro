"""A crude thermal model: rooms warm while a valve is open and lose heat to the outside."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import random

from .house import OUTDOOR_START, ROOMS, Room

HEAT_RATE = 1.6  # K/h of air warming with every valve of the room open
WINDOW_FACTOR = 10.0  # an open window multiplies the heat loss
BIAS_OPEN = 3.0  # the TRV sits at the radiator: it reads this much above the air while heating
BIAS_CLOSED = 0.8
BIAS_TAU = 0.25  # h, how fast the radiator warms up or cools down
VALVE_OPEN_BELOW = 0.3  # the valve opens when the TRV reads this far below its setpoint …
VALVE_CLOSE_ABOVE = 0.2  # … and closes this far above it


@dataclass
class TrvState:
    """What a thermostat knows: mode, setpoint, its own reading, the valve."""

    hvac_mode: str = "heat"
    setpoint: float = 18.0
    bias: float = BIAS_CLOSED
    valve_open: bool = False
    available: bool = True


@dataclass
class RoomState:
    """Air temperature, humidity and the room's thermostats and windows."""

    room: Room
    air: float
    humidity: float
    trvs: dict[str, TrvState]
    windows: dict[str, bool]


@dataclass
class Simulation:
    """The whole house; entities subscribe and are told after every change."""

    outdoor: float = OUTDOOR_START
    rooms: dict[str, RoomState] = field(default_factory=dict)
    _listeners: list[Callable[[], None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Start every room near its configured temperature."""
        rng = random.Random(7)
        for room in ROOMS:
            self.rooms[room.name] = RoomState(
                room=room,
                air=room.start,
                humidity=round(rng.uniform(45, 60), 1),
                trvs={t.object_id: TrvState() for t in room.trvs},
                windows={w.object_id: False for w in room.windows},
            )

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call `listener` after every change; returns the unsubscribe function."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def notify(self) -> None:
        """Tell every entity to write its state."""
        for listener in list(self._listeners):
            listener()

    def room_of_trv(self, object_id: str) -> RoomState:
        """The room a thermostat belongs to."""
        return next(r for r in self.rooms.values() if object_id in r.trvs)

    def room_of_window(self, object_id: str) -> RoomState:
        """The room a window belongs to."""
        return next(r for r in self.rooms.values() if object_id in r.windows)

    def trv_reading(self, object_id: str) -> float:
        """What the thermostat's own sensor reads (above the air, more so while heating)."""
        room = self.room_of_trv(object_id)
        return room.air + room.trvs[object_id].bias

    def step(self, hours: float) -> None:
        """Advance the model by `hours`."""
        for room in self.rooms.values():
            open_valves = 0
            for trv in room.trvs.values():
                reading = room.air + trv.bias
                if trv.hvac_mode != "heat" or not trv.available:
                    trv.valve_open = False
                elif reading < trv.setpoint - VALVE_OPEN_BELOW:
                    trv.valve_open = True
                elif reading > trv.setpoint + VALVE_CLOSE_ABOVE:
                    trv.valve_open = False
                target_bias = BIAS_OPEN if trv.valve_open else BIAS_CLOSED
                trv.bias += (target_bias - trv.bias) * min(1.0, hours / BIAS_TAU)
                open_valves += trv.valve_open
            heating = HEAT_RATE * open_valves / len(room.trvs)
            loss = room.room.loss * (room.air - self.outdoor)
            if any(room.windows.values()):
                loss *= WINDOW_FACTOR
            room.air += (heating - loss) * hours
        self.notify()
