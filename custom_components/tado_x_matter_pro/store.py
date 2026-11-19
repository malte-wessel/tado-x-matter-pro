"""Persistence: per room its temperatures, the engine state, the thermostats' last state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NotRequired, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_HEATING_TEMPERATURE,
    DEFAULT_IDLE_TEMPERATURE,
    STORAGE_KEY,
    STORAGE_MINOR_VERSION,
    STORAGE_VERSION,
)
from .engine.model import Boost, Expiry, Override, RoomState, WindowPhase


class OverrideDict(TypedDict):
    """An override as stored; `expires` is an Expiry value or an ISO timestamp."""

    temperature: float | None
    expires: str
    window_ack: bool
    preset: str | None


class BoostDict(TypedDict):
    """A boost as stored."""

    temperature: float
    until: str


class StateDict(TypedDict):
    """The engine's room state as stored."""

    window: str
    window_deadline: str | None
    override: OverrideDict | None
    boost: BoostDict | None
    plan_key: list[Any] | None
    frost_active: bool
    bounces: list[str]
    window_open_since: str | None
    reminded: bool


class RoomDict(TypedDict):
    """One room as stored."""

    heating_temperature: float
    idle_temperature: float
    state: NotRequired[StateDict]
    # Last mode and setpoint each thermostat was known to have; tells changes made while
    # Home Assistant was down.
    last_known: dict[str, list[Any]]
    # What the integration sent each thermostat last (stored before sending): a write still on its
    # way when Home Assistant stopped is no change made while it was down.
    last_commanded: NotRequired[dict[str, list[Any]]]


class StoreData(TypedDict):
    """The whole store, rooms by subentry id."""

    rooms: dict[str, RoomDict]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def state_to_dict(state: RoomState) -> StateDict:
    """Serialize the engine state."""
    override = state.override
    return {
        "window": str(state.window),
        "window_deadline": _iso(state.window_deadline),
        "override": None
        if override is None
        else {
            "temperature": override.temperature,
            "expires": override.expires.isoformat()
            if isinstance(override.expires, datetime)
            else str(override.expires),
            "window_ack": override.window_ack,
            "preset": override.preset,
        },
        "boost": None
        if state.boost is None
        else {"temperature": state.boost.temperature, "until": state.boost.until.isoformat()},
        "plan_key": list(state.plan_key) if state.plan_key is not None else None,
        "frost_active": state.frost_active,
        "bounces": [t.isoformat() for t in state.bounces],
        "window_open_since": _iso(state.window_open_since),
        "reminded": state.reminded,
    }


def state_from_dict(data: StateDict | None) -> RoomState:
    """Rebuild the engine state; a missing or unreadable state starts fresh."""
    if not data:
        return RoomState()
    override = None
    if (stored := data.get("override")) is not None:
        expires_raw = stored["expires"]
        expires: Expiry | datetime = (
            Expiry(expires_raw)
            if expires_raw in set(Expiry)
            else datetime.fromisoformat(expires_raw)
        )
        override = Override(
            stored["temperature"], expires, stored.get("window_ack", False), stored.get("preset")
        )
    boost = None
    if (stored_boost := data.get("boost")) is not None:
        boost = Boost(stored_boost["temperature"], datetime.fromisoformat(stored_boost["until"]))
    key = data.get("plan_key")
    return RoomState(
        window=WindowPhase(data.get("window", WindowPhase.CLOSED)),
        window_deadline=_dt(data.get("window_deadline")),
        override=override,
        boost=boost,
        plan_key=(key[0], key[1], key[2], key[3]) if key else None,
        frost_active=data.get("frost_active", False),
        bounces=[datetime.fromisoformat(t) for t in data.get("bounces", [])],
        window_open_since=_dt(data.get("window_open_since")),
        reminded=data.get("reminded", False),
    )


def _migrate_room(room: dict[str, Any], minor: int) -> None:
    """Bring one stored room from store 1.`minor` to the current minor version."""
    state = room.get("state")
    if minor < 3:  # 1.2 kept an inferred heating status; 1.3 takes it from demand entities
        room.pop("status", None)
    if minor < 4 and state is not None:  # 1.4: boost, and the preset that made an override
        state.setdefault("boost", None)
        if state.get("override") is not None:
            state["override"].setdefault("preset", None)
    if minor < 5 and state is not None:  # 1.5: since when a window keeps the room off, reminded
        state.setdefault("window_open_since", None)
        state.setdefault("reminded", False)
    if minor < 6:  # 1.6: what was sent last per thermostat
        room.setdefault("last_commanded", {})


class _Storage(Store[StoreData]):
    """The HA store with the schema migrations.

    Bump STORAGE_MINOR_VERSION for additive changes and fill the new keys here; bump
    STORAGE_VERSION for breaking ones and convert the old shape. Home Assistant refuses a store
    written by a newer major version.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> StoreData:
        rooms = old_data.get("rooms", {})
        if old_major_version == 1:
            for room in rooms.values():
                _migrate_room(room, old_minor_version)
        return {"rooms": rooms}


@dataclass
class HeatingStore:
    """Loads and saves the rooms."""

    hass: HomeAssistant
    data: StoreData = field(default_factory=lambda: StoreData(rooms={}))
    _store: Store[StoreData] = field(init=False)

    def __post_init__(self) -> None:
        """Create the underlying store."""
        self._store = _Storage(
            self.hass, STORAGE_VERSION, STORAGE_KEY, minor_version=STORAGE_MINOR_VERSION
        )

    async def async_load(self, room_ids: set[str]) -> None:
        """Load from disk and drop rooms that no longer exist."""
        loaded = await self._store.async_load()
        if loaded is not None:
            self.data = loaded
        rooms = self.data["rooms"]
        removed = set(rooms) - room_ids
        for room_id in removed:
            del rooms[room_id]
        if removed:  # a room was removed: its state goes from disk too, not just at the next save
            await self._store.async_save(self.data)

    def room(self, room_id: str) -> RoomDict:
        """Return the stored room, created with defaults on first use."""
        return self.data["rooms"].setdefault(
            room_id,
            {
                "heating_temperature": DEFAULT_HEATING_TEMPERATURE,
                "idle_temperature": DEFAULT_IDLE_TEMPERATURE,
                "last_known": {},
            },
        )

    def save(self) -> None:
        """Schedule a write to disk."""
        self._store.async_delay_save(lambda: self.data, 1)

    async def async_flush(self) -> None:
        """Write now (on unload, so a reload starts from the latest state)."""
        await self._store.async_save(self.data)

    async def async_remove(self) -> None:
        """Delete the data from disk (the integration was removed)."""
        await self._store.async_remove()
