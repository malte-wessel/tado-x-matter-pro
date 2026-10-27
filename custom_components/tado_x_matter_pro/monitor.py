"""Whether each thermostat of a room is heating: the trends of their readings, the status."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from itertools import pairwise
import logging
from typing import Any

from homeassistant.components.recorder import history
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    EventStateReportedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_state_report_event,
)
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util

from .engine.inference import Status, infer, room_status
from .engine.trend import WINDOW, Trend

_LOGGER = logging.getLogger(__name__)

SEED = WINDOW + timedelta(minutes=5)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _value(state: State | None) -> float | None:
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    return _float(state.state)


class HeatingMonitor:
    """Trends and statuses of a room's thermostats; tells the room when a status changes."""

    def __init__(
        self,
        hass: HomeAssistant,
        thermostats: list[str],
        statuses: dict[str, str],
        on_change: Callable[[bool], None],
    ) -> None:
        """`statuses` is the room's stored dict of previous statuses (the rule's hysteresis).

        `on_change(status_changed)` is called after every new reading or trend.
        """
        self.hass = hass
        self.thermostats = thermostats
        self._statuses = statuses
        self._on_change = on_change
        self.sensors: dict[str, str | None] = {}
        self._by_sensor: dict[str, str] = {}
        self.trends: dict[str, Trend] = {eid: Trend() for eid in thermostats}
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._unsubs: list[CALLBACK_TYPE] = []

    # --- what the room and its entities read ---

    def status(self, thermostat: str) -> Status:
        """Return the thermostat's inferred status."""
        stored = self._statuses.get(thermostat)
        return Status(stored) if stored in set(Status) else Status.OFF

    def trend(self, thermostat: str) -> float | None:
        """Return the trend of the thermostat's reading in °C/h."""
        return self.trends[thermostat].value

    def reading(self, thermostat: str) -> float | None:
        """Return the thermostat's own reading (the precise sensor if there is one)."""
        sensor = self.sensors.get(thermostat)
        if sensor is not None and (value := _value(self.hass.states.get(sensor))) is not None:
            return value
        state = self.hass.states.get(thermostat)
        return _float(state.attributes.get("current_temperature")) if state else None

    @property
    def room_status(self) -> Status:
        """The most active status of the room's thermostats."""
        return room_status([self.status(eid) for eid in self.thermostats])

    # --- lifecycle ---

    async def async_start(self) -> None:
        """Find each thermostat's temperature sensor, seed the trends, follow the sensors."""
        self.sensors = {eid: self._find_sensor(eid) for eid in self.thermostats}
        await self._async_seed()
        self._by_sensor = {s: eid for eid, s in self.sensors.items() if s is not None}
        if self._by_sensor:
            sensors = list(self._by_sensor)
            self._unsubs.append(
                async_track_state_change_event(self.hass, sensors, self._on_sensor_changed)
            )
            self._unsubs.append(
                async_track_state_report_event(self.hass, sensors, self._on_sensor_reported)
            )
        for thermostat in self.thermostats:
            self._evaluate(thermostat)

    @callback
    def async_stop(self) -> None:
        """Stop following and cancel the recalculation timers."""
        for unsub in (*self._unsubs, *self._timers.values()):
            unsub()
        self._unsubs.clear()
        self._timers.clear()

    def _find_sensor(self, thermostat: str) -> str | None:
        """Return the temperature sensor on the thermostat's device (Tado X: 0.01 °C)."""
        registry = er.async_get(self.hass)
        entry = registry.async_get(thermostat)
        if entry is None or entry.device_id is None:
            return None
        candidates = [
            e
            for e in er.async_entries_for_device(registry, entry.device_id)
            if e.domain == "sensor"
            and (e.device_class or e.original_device_class) == "temperature"
            and e.disabled_by is None
        ]
        candidates.sort(key=lambda e: e.platform != entry.platform)  # same integration first
        return candidates[0].entity_id if candidates else None

    async def _async_seed(self) -> None:
        """Fill the trends from the recorder, so they are right from the first minute."""
        if "recorder" not in self.hass.config.components:
            return
        end = dt_util.utcnow()
        for thermostat, sensor in self.sensors.items():
            if sensor is None:
                continue
            try:
                result = await get_instance(self.hass).async_add_executor_job(
                    history.state_changes_during_period, self.hass, end - SEED, end, sensor
                )
            except Exception:
                _LOGGER.debug("No history to seed the trend of %s", sensor, exc_info=True)
                continue
            trend = self.trends[thermostat]
            for old, new in pairwise(result.get(sensor, [])):
                trend.changed(_value(old), old.last_reported, _value(new), new.last_updated)

    # --- events ---

    @callback
    def _on_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        thermostat = self._by_sensor[event.data["entity_id"]]
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None:
            return
        next_at = self.trends[thermostat].changed(
            _value(old),
            old.last_reported if old else new.last_updated,
            _value(new),
            new.last_updated,
        )
        self._schedule(thermostat, next_at)
        self._evaluate(thermostat)

    @callback
    def _on_sensor_reported(self, event: Event[EventStateReportedData]) -> None:
        thermostat = self._by_sensor[event.data["entity_id"]]
        new = event.data["new_state"]
        next_at = self.trends[thermostat].reported(
            _value(new), event.data["old_last_reported"], event.data["last_reported"]
        )
        self._schedule(thermostat, next_at)
        self._evaluate(thermostat)

    @callback
    def thermostat_changed(self, event: Event[EventStateChangedData]) -> None:
        """Mode, setpoint or reading of a thermostat changed (called by the room)."""
        thermostat = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        if self.sensors.get(thermostat) is None and new is not None:
            # No precise sensor: follow the climate's own (0.1 °C) reading instead.
            new_value = _float(new.attributes.get("current_temperature"))
            old_value = _float(old.attributes.get("current_temperature")) if old else None
            if new_value is not None and new_value != old_value:
                next_at = self.trends[thermostat].changed(
                    old_value,
                    old.last_reported if old else new.last_updated,
                    new_value,
                    new.last_updated,
                )
                self._schedule(thermostat, next_at)
        self._evaluate(thermostat)

    def _schedule(self, thermostat: str, when: datetime | None) -> None:
        if (cancel := self._timers.pop(thermostat, None)) is not None:
            cancel()
        if when is None:
            return

        @callback
        def _tick(_scheduled: datetime) -> None:
            self._timers.pop(thermostat, None)
            # Like the derivative sensor: computed for the moment the timer actually fires.
            self._schedule(thermostat, self.trends[thermostat].tick(dt_util.utcnow()))
            self._evaluate(thermostat)

        self._timers[thermostat] = async_track_point_in_utc_time(self.hass, _tick, when)

    def _evaluate(self, thermostat: str) -> None:
        state = self.hass.states.get(thermostat)
        previous = self.status(thermostat) if thermostat in self._statuses else None
        status = infer(
            state.state if state else None,
            _float(state.attributes.get("temperature")) if state else None,
            # The rule was tuned on the climate's own reading (0.1 °C), as Tado X reports it.
            _float(state.attributes.get("current_temperature")) if state else None,
            self.trends[thermostat].value,
            previous,
        )
        changed = status != previous
        if changed:
            self._statuses[thermostat] = str(status)
        self._on_change(changed)
