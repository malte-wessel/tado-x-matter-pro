"""One room in Home Assistant: reads its inputs, runs the engine, writes its thermostats."""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
import logging
from statistics import fmean
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLOSE_DELAY,
    CONF_FROST_TEMPERATURE,
    CONF_IDLE_SENSORS,
    CONF_OPEN_DELAY,
    CONF_ROOM_SENSOR,
    CONF_SCHEDULE,
    CONF_THERMOSTATS,
    CONF_WINDOWS,
    DEFAULT_CLOSE_DELAY_MINUTES,
    DEFAULT_FROST_TEMPERATURE,
    DEFAULT_OPEN_DELAY_SECONDS,
    SECTION_WINDOW,
)
from .engine.external import SETTLE, Command, Report, TrvView, classify
from .engine.model import Desired, Inputs, RoomConfig, RoomState
from .engine.room import Event as RoomEvent, ExternalChange, Resume, SetMode, SetTemperature, step
from .monitor import HeatingMonitor
from .store import HeatingStore, RoomDict, state_from_dict, state_to_dict

_LOGGER = logging.getLogger(__name__)

# A dial turn reports every half degree; act on the last one.
EXTERNAL_COALESCE = timedelta(seconds=4)
TOLERANCE = 0.05
# Entries kept for diagnostics: reports, decisions and writes.
TRACE_LENGTH = 200


def _duration(value: dict[str, Any] | None, default: timedelta) -> timedelta:
    return timedelta(**value) if value else default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


class RoomController:
    """Glue between Home Assistant and the engine for one room (one subentry)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        store: HeatingStore,
    ) -> None:
        """Read the room's configuration and its stored state."""
        self.hass = hass
        self.entry = entry
        self.room_id = subentry.subentry_id
        self.name = subentry.title
        data = subentry.data
        self.thermostats: list[str] = list(data[CONF_THERMOSTATS])
        self.schedule: str = data[CONF_SCHEDULE]
        self.windows: list[str] = list(data.get(CONF_WINDOWS, []))
        self.room_sensor: str | None = data.get(CONF_ROOM_SENSOR)
        window = data.get(SECTION_WINDOW, {})
        self.config = RoomConfig(
            open_delay=_duration(
                window.get(CONF_OPEN_DELAY), timedelta(seconds=DEFAULT_OPEN_DELAY_SECONDS)
            ),
            close_delay=_duration(
                window.get(CONF_CLOSE_DELAY), timedelta(minutes=DEFAULT_CLOSE_DELAY_MINUTES)
            ),
            frost_temperature=float(
                entry.options.get(CONF_FROST_TEMPERATURE, DEFAULT_FROST_TEMPERATURE)
            ),
        )
        self.idle_sensors: list[str] = list(entry.options.get(CONF_IDLE_SENSORS, []))
        self._store = store
        self._stored: RoomDict = store.room(self.room_id)
        self.state: RoomState = state_from_dict(self._stored.get("state"))
        self.inputs: Inputs | None = None
        self.desired: Desired | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._wakeup: CALLBACK_TYPE | None = None
        self._external_timer: CALLBACK_TYPE | None = None
        self._pending_external: ExternalChange | None = None
        self._views: dict[str, TrvView] = {}
        self._commands: dict[str, Command] = {}
        # Last available state of each input: an unavailable one keeps its last known state.
        self._known: dict[str, State] = {}
        self._reconcile_task: asyncio.Task[None] | None = None
        self._reconcile_again = False
        self.monitor = HeatingMonitor(
            hass, self.thermostats, self._stored.setdefault("status", {}), self._statuses_changed
        )
        self.trace: deque[dict[str, Any]] = deque(maxlen=TRACE_LENGTH)
        self.counters: Counter[str] = Counter()

    # --- what entities read and call ---

    @property
    def heating_temperature(self) -> float:
        """The room's heating temperature (during schedule blocks)."""
        return self._stored["heating_temperature"]

    @property
    def idle_temperature(self) -> float:
        """The room's idle temperature (outside blocks and while away)."""
        return self._stored["idle_temperature"]

    @property
    def area_name(self) -> str | None:
        """The area of the first thermostat, for the room device."""
        entry = er.async_get(self.hass).async_get(self.thermostats[0])
        if entry is None:
            return None
        area_id = entry.area_id
        if area_id is None and entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            area_id = device.area_id if device else None
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        return area.name if area else None

    @property
    def next_change(self) -> datetime | None:
        """When the schedule switches next."""
        state = self.hass.states.get(self.schedule)
        value = state.attributes.get("next_event") if state else None
        return value if isinstance(value, datetime) else None

    @callback
    def add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call `listener` after every decision; returns the unsubscribe function."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def set_temperature(self, temperature: float) -> None:
        """Hold a temperature set on the room thermostat."""
        self._run(SetTemperature(temperature))

    @callback
    def set_mode(self, mode: str) -> None:
        """Auto (plan), heat (hold) or off, from the room thermostat."""
        self._run(SetMode(mode))

    @callback
    def resume(self) -> None:
        """Back to the schedule."""
        self._run(Resume())

    @callback
    def set_number(self, key: str, value: float) -> None:
        """Change the heating or idle temperature."""
        if key == "heating_temperature":
            self._stored["heating_temperature"] = value
        else:
            self._stored["idle_temperature"] = value
        self._store.save()
        self._run()

    def diagnostics(self) -> dict[str, Any]:
        """Everything that explains the room's behaviour, for a bug report."""
        monitor = self.monitor
        return {
            "name": self.name,
            "thermostats": self.thermostats,
            "schedule": self.schedule,
            "windows": self.windows,
            "room_sensor": self.room_sensor,
            "idle_sensors": self.idle_sensors,
            "config": {
                "open_delay": self.config.open_delay.total_seconds(),
                "close_delay": self.config.close_delay.total_seconds(),
                "frost_temperature": self.config.frost_temperature,
            },
            "stored": self._stored,
            "inputs": asdict(self.inputs) if self.inputs else None,
            "desired": asdict(self.desired) if self.desired else None,
            "views": {eid: asdict(view) for eid, view in self._views.items()},
            "commands": {
                eid: {**asdict(command), "context_ids": sorted(command.context_ids)}
                for eid, command in self._commands.items()
            },
            "pending_external": asdict(self._pending_external) if self._pending_external else None,
            "heating": {
                eid: {
                    "sensor": monitor.sensors.get(eid),
                    "status": monitor.status(eid),
                    "reading": monitor.reading(eid),
                    "trend": monitor.trend(eid),
                }
                for eid in self.thermostats
            },
            "counters": dict(self.counters),
            "trace": list(self.trace),
        }

    def _trace(self, what: str, **details: Any) -> None:
        self.trace.append({"at": dt_util.utcnow().isoformat(), "what": what, **details})

    # --- lifecycle ---

    async def async_start(self) -> None:
        """Snapshot the thermostats, follow every input, decide."""
        self._views = {eid: self._view(eid) for eid in self.thermostats}
        await self.monitor.async_start()
        inputs = [self.schedule, *self.idle_sensors, *self.windows]
        if self.room_sensor:
            inputs.append(self.room_sensor)
        self._unsubs.append(async_track_state_change_event(self.hass, inputs, self._on_input))
        self._unsubs.append(
            async_track_state_change_event(self.hass, self.thermostats, self._on_thermostat)
        )
        self._run(self._changed_while_down())

    @callback
    def async_stop(self) -> None:
        """Stop following and cancel timers and writes."""
        for unsub in (*self._unsubs, self._wakeup, self._external_timer):
            if unsub is not None:
                unsub()
        self._unsubs.clear()
        self._wakeup = self._external_timer = None
        self.monitor.async_stop()
        if self._reconcile_task is not None:
            self._reconcile_task.cancel()

    # --- inputs ---

    def _view(self, entity_id: str) -> TrvView:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return TrvView(available=False)
        return TrvView(
            available=True,
            hvac_mode=state.state,
            setpoint=_float(state.attributes.get("temperature")),
        )

    def _known_state(self, entity_id: str) -> State | None:
        """Return the input's state, or its last available one while it is unavailable."""
        state = self.hass.states.get(entity_id)
        if state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._known[entity_id] = state
        return self._known.get(entity_id)

    def _read_inputs(self) -> Inputs:
        # Inputs not known since the start keep the last decision (the stored plan key), so a
        # sensor that is slow to come up after a restart neither switches the plan nor ends holds.
        last = self.state.plan_key
        schedule = self._known_state(self.schedule)
        if schedule is not None:
            schedule_on = schedule.state == STATE_ON
            block = _float(schedule.attributes.get("temperature")) if schedule_on else None
        else:
            schedule_on, block = (last[0], last[1]) if last else (False, None)
        idle_states = [self._known_state(e) for e in self.idle_sensors]
        idle = any(s is not None and s.state == STATE_ON for s in idle_states)
        if not idle and last and None in idle_states:
            idle = last[2]
        return Inputs(
            schedule_on=schedule_on,
            block_temperature=block,
            idle=idle,
            heating_temperature=self.heating_temperature,
            idle_temperature=self.idle_temperature,
            window_open=any(
                (s := self._known_state(e)) is not None and s.state == STATE_ON
                for e in self.windows
            ),
            room_temperature=self._room_temperature(),
        )

    def _room_temperature(self) -> float | None:
        if self.room_sensor and (state := self.hass.states.get(self.room_sensor)):
            value = _float(state.state)
            if value is not None:
                return value
        readings = [
            value
            for eid in self.thermostats
            if (state := self.hass.states.get(eid)) is not None
            and (value := _float(state.attributes.get("current_temperature"))) is not None
        ]
        return round(fmean(readings), 1) if readings else None

    @callback
    def _on_input(self, _event: Event[EventStateChangedData]) -> None:
        self._run()

    @callback
    def _on_thermostat(self, event: Event[EventStateChangedData]) -> None:
        self.monitor.thermostat_changed(event)
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        old = self._views.get(entity_id)
        new = self._view(entity_id)
        self._views[entity_id] = new
        desired = (
            (self.desired.hvac_mode, self.desired.temperature) if self.desired else ("heat", None)
        )
        report = classify(
            old,
            new,
            desired=desired,
            command=self._commands.get(entity_id),
            context_id=new_state.context.id if new_state else None,
            now=dt_util.utcnow(),
        )
        self.counters[f"report_{report}"] += 1
        if report is not Report.IGNORED:
            self._trace(
                "report",
                thermostat=entity_id,
                report=report,
                old=[old.hvac_mode, old.setpoint] if old else None,
                new=[new.hvac_mode, new.setpoint],
            )
        elif old is None or old.available != new.available:
            self._trace("availability", thermostat=entity_id, available=new.available)
        if report in (Report.OURS, Report.CONVERGED, Report.EXTERNAL):
            self._remember(entity_id, new)
        if report is Report.EXTERNAL:
            _LOGGER.debug("%s: %s changed externally to %s", self.name, entity_id, new)
            self._pending_external = ExternalChange(new.hvac_mode or "off", new.setpoint)
            if self._external_timer is not None:
                self._external_timer()
            self._external_timer = async_call_later(
                self.hass, EXTERNAL_COALESCE, self._fire_external
            )
            return
        # Readings changed, or a thermostat came back: decide again (writes only on deviation).
        self._run()

    @callback
    def _fire_external(self, _now: datetime) -> None:
        self._external_timer = None
        change, self._pending_external = self._pending_external, None
        if change is not None:
            self._run(change)

    @callback
    def _statuses_changed(self, status_changed: bool) -> None:  # noqa: FBT001
        if status_changed:
            self._store.save()
        for listener in list(self._listeners):
            listener()

    def _remember(self, entity_id: str, view: TrvView) -> None:
        known = [view.hvac_mode, view.setpoint]
        if self._stored["last_known"].get(entity_id) != known:
            self._stored["last_known"][entity_id] = known
            self._store.save()

    def _changed_while_down(self) -> ExternalChange | None:
        """Return a change made while HA was down: a thermostat differs from what we knew."""
        for entity_id, view in self._views.items():
            known = self._stored["last_known"].get(entity_id)
            if not known or not view.available:
                continue
            mode, setpoint = known
            setpoint_differs = (
                view.setpoint is None
                or setpoint is None
                or abs(view.setpoint - setpoint) > TOLERANCE
            )
            if view.hvac_mode != mode or (view.hvac_mode == "heat" and setpoint_differs):
                return ExternalChange(view.hvac_mode or "off", view.setpoint)
        return None

    # --- deciding ---

    @callback
    def _run(self, event: RoomEvent | None = None) -> None:
        self.inputs = self._read_inputs()
        result = step(self.state, self.inputs, self.config, dt_util.utcnow(), event)
        if event is not None:
            _LOGGER.debug("%s: %s → %s", self.name, event, result.desired)
        if event is not None or result.desired != self.desired:
            self._trace(
                "decision",
                event=repr(event) if event else None,
                desired=asdict(result.desired),
                window=result.state.window,
            )
        self.state = result.state
        self.desired = result.desired
        # Most runs are readings that change nothing: write to disk only when the state changed.
        stored = state_to_dict(self.state)
        if stored != self._stored.get("state"):
            self._stored["state"] = stored
            self._store.save()
        self._schedule_wakeup(result.next_wakeup)
        for listener in list(self._listeners):
            listener()
        self._schedule_reconcile()

    def _schedule_wakeup(self, when: datetime | None) -> None:
        if self._wakeup is not None:
            self._wakeup()
            self._wakeup = None
        if when is not None:
            self._wakeup = async_track_point_in_utc_time(self.hass, self._on_wakeup, when)

    @callback
    def _on_wakeup(self, _now: datetime) -> None:
        self._wakeup = None
        self._run()

    # --- writing the thermostats ---

    def _schedule_reconcile(self) -> None:
        if self._reconcile_task is not None and not self._reconcile_task.done():
            self._reconcile_again = True
            return
        self._reconcile_task = self.entry.async_create_background_task(
            self.hass, self._async_reconcile(), f"tado_x_matter_pro reconcile {self.name}"
        )

    async def _async_reconcile(self) -> None:
        while True:
            self._reconcile_again = False
            for entity_id in self.thermostats:
                await self._async_write(entity_id)
            if not self._reconcile_again:
                return

    async def _async_write(self, entity_id: str) -> None:
        desired = self.desired
        view = self._view(entity_id)
        if desired is None or not view.available or self._pending_external is not None:
            # While a dial turn settles, the old target would turn it back; it becomes the hold.
            return
        want = (desired.hvac_mode, desired.temperature)
        if view.hvac_mode == want[0] and (
            want[0] == "off"
            or (
                view.setpoint is not None
                and want[1] is not None
                and abs(view.setpoint - want[1]) <= TOLERANCE
            )
        ):
            return
        now = dt_util.utcnow()
        last = self._commands.get(entity_id)
        if last is not None and last.want == want and now - (last.returned_at or now) < SETTLE:
            return  # already sent, the reports are still on their way
        context = Context()
        command = Command(
            prev=(view.hvac_mode, view.setpoint), want=want, issued_at=now, context_ids={context.id}
        )
        self._commands[entity_id] = command
        self.counters["write"] += 1
        self._trace("write", thermostat=entity_id, want=list(want), context_id=context.id)
        try:
            if want[0] == "off":
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "off"},
                    blocking=True,
                    context=context,
                )
            else:
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": entity_id, "temperature": want[1], "hvac_mode": "heat"},
                    blocking=True,
                    context=context,
                )
        except HomeAssistantError as err:
            _LOGGER.warning("%s: writing %s failed: %s", self.name, entity_id, err)
            self._commands.pop(entity_id, None)
            self.counters["write_failed"] += 1
            self._trace("write_failed", thermostat=entity_id, error=str(err))
        finally:
            command.returned_at = dt_util.utcnow()
