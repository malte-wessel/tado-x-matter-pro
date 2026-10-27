"""The simulated house: floors, rooms, thermostats, windows and room sensors (all fictional)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Trv:
    """A Tado X-like radiator thermostat; `object_id` is the climate entity's object id."""

    object_id: str
    name: str


@dataclass(frozen=True)
class Window:
    """A window or door contact."""

    object_id: str
    name: str
    door: bool = False


@dataclass(frozen=True)
class Room:
    """A heated room."""

    name: str
    floor: str
    icon: str
    trvs: tuple[Trv, ...]
    windows: tuple[Window, ...] = ()
    # Object id of a separate room temperature sensor (a presence sensor), if the room has one.
    room_sensor: str | None = None
    # Starting air temperature and how well the room keeps its heat (loss per hour and kelvin).
    start: float = 19.5
    loss: float = 0.08
    trvs_by_id: dict[str, Trv] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Index the thermostats."""
        object.__setattr__(self, "trvs_by_id", {t.object_id: t for t in self.trvs})


FLOORS: tuple[tuple[str, int, str], ...] = (
    ("Ground Floor", 0, "mdi:home-floor-0"),
    ("First Floor", 1, "mdi:home-floor-1"),
    ("Attic", 2, "mdi:home-floor-2"),
)

ROOMS: tuple[Room, ...] = (
    Room(
        "Living Room",
        "Ground Floor",
        "mdi:sofa",
        (Trv("living_room_thermostat", "Thermostat Living Room"),),
        (Window("living_room_terrace_door", "Terrace Door", door=True),),
        room_sensor="living_room_temperature",
        start=20.4,
    ),
    Room(
        "Kitchen",
        "Ground Floor",
        "mdi:stove",
        (Trv("kitchen_thermostat", "Thermostat Kitchen"),),
        (Window("kitchen_window", "Kitchen Window"),),
        room_sensor="kitchen_temperature",
        start=20.1,
    ),
    Room(
        "Hallway",
        "Ground Floor",
        "mdi:door",
        (Trv("hallway_thermostat", "Thermostat Hallway"),),
        (Window("front_door", "Front Door", door=True),),
        start=18.9,
        loss=0.12,
    ),
    Room(
        "Toilet",
        "Ground Floor",
        "mdi:toilet",
        (Trv("toilet_thermostat", "Thermostat Toilet"),),
        (Window("toilet_window", "Toilet Window"),),
        room_sensor="toilet_temperature",
        start=19.2,
    ),
    Room(
        "Bedroom",
        "First Floor",
        "mdi:bed",
        (Trv("bedroom_thermostat", "Thermostat Bedroom"),),
        (
            Window("bedroom_window_left", "Bedroom Window Left"),
            Window("bedroom_window_right", "Bedroom Window Right"),
        ),
        start=18.4,
    ),
    Room(
        "Kids Room",
        "First Floor",
        "mdi:human-child",
        (Trv("kids_room_thermostat", "Thermostat Kids Room"),),
        (Window("kids_room_window", "Kids Room Window"),),
        start=19.0,
    ),
    Room(
        "Bathroom",
        "First Floor",
        "mdi:shower",
        (
            Trv("bathroom_thermostat", "Thermostat Bathroom"),
            Trv("bathroom_thermostat_tub", "Thermostat Bathroom Tub"),
        ),
        (Window("bathroom_window", "Bathroom Window"),),
        room_sensor="bathroom_temperature",
        start=20.8,
    ),
    Room(
        "Upstairs Hallway",
        "First Floor",
        "mdi:door",
        (Trv("upstairs_hallway_thermostat", "Thermostat Upstairs Hallway"),),
        (Window("upstairs_hallway_window", "Upstairs Hallway Window"),),
        room_sensor="upstairs_hallway_temperature",
        start=18.6,
    ),
    Room(
        "Office",
        "Attic",
        "mdi:home-roof",
        (
            Trv("office_thermostat_front", "Thermostat Office Front"),
            # Left with the default name, as freshly paired Tado X thermostats are.
            Trv("smart_radiator_thermostat_x", "Smart Radiator Thermostat X"),
        ),
        (
            Window("office_window_front", "Office Window Front"),
            Window("office_window_back", "Office Window Back"),
        ),
        room_sensor="office_temperature",
        start=19.7,
        loss=0.1,
    ),
)

OUTDOOR_START = 8.0
