"""One room in Home Assistant: reads its inputs, runs the engine, writes its thermostats."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import datetime, time, timedelta
from functools import partial
import logging
import random
from statistics import fmean
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    EventStateReportedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_state_report_event,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BOOST_DURATION,
    CONF_BOOST_TEMPERATURE,
    CONF_CLOSE_DELAY,
    CONF_DEMAND,
    CONF_DEMAND_THRESHOLD,
    CONF_FROST_TEMPERATURE,
    CONF_IDLE_SENSORS,
    CONF_NOTIFY,
    CONF_ONLY_BELOW,
    CONF_OPEN_DELAY,
    CONF_OUTDOOR_SENSOR,
    CONF_REMIND_AFTER,
    CONF_ROOM_SENSOR,
    CONF_SCHEDULE,
    CONF_THERMOSTATS,
    CONF_WINDOWS,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_BOOST_TEMPERATURE,
    DEFAULT_CLOSE_DELAY_MINUTES,
    DEFAULT_DEMAND_THRESHOLD,
    DEFAULT_FROST_TEMPERATURE,
    DEFAULT_OPEN_DELAY_SECONDS,
    DEFAULT_REMIND_AFTER_MINUTES,
    DOMAIN,
    EVENT_ROOM,
    SECTION_BOOST,
    SECTION_REMINDER,
    SECTION_WINDOW,
    START_GRACE,
)
from .engine.external import Report, TrvView, classify, matches
from .engine.forecast import HORIZON, Block, Forecast, forecast
from .engine.heating import Status, room_action, status as heating_status
from .engine.log import Kind, entries as log_entries
from .engine.model import Desired, Inputs, RoomConfig, RoomState, WindowPhase
from .engine.room import (
    EndPreset,
    Event as RoomEvent,
    ExtendBlock,
    ExternalChange,
    NumberChanged,
    Resume,
    SetMode,
    SetOverride,
    SetTemperature,
    StartBoost,
    step,
)
from .house import entity_missing
from .messages import reminder
from .store import HeatingStore, RoomDict, state_from_dict, state_to_dict
from .trv import TrvWriter

_LOGGER = logging.getLogger(__name__)

# A dial turn reports every half degree; act on the last one.
EXTERNAL_COALESCE = timedelta(seconds=4)
TOLERANCE = 0.05
# Entries kept for diagnostics: reports, decisions and writes.
TRACE_LENGTH = 200
# Repair issues: a window contact bouncing this often within the engine's bounce window (an hour),
# and a contact unavailable this long while it last said open (the room stays off meanwhile).
CHATTER_BOUNCES = 10
CONTACT_ISSUE_AFTER = timedelta(minutes=30)
# Writes for a schedule edge or an away change wait a random part of this per room, so that a
# house full of valves does not transmit in the same second.
PLAN_EDGE_SPREAD = timedelta(seconds=45)


def random_delay() -> timedelta:
    """Return the delay of one room's writes for a schedule edge or away change."""
    return timedelta(seconds=random.uniform(0, PLAN_EDGE_SPREAD.total_seconds()))  # noqa: S311


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        if value.startswith("24:00"):
            return time.max
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None
    return None


def expand_week(week: Mapping[str, Any], now: datetime) -> list[Block]:
    """Turn a schedule's weekly blocks (local times) into dated blocks in UTC around `now`."""
    zone = dt_util.get_default_time_zone()
    today = dt_util.as_local(now).date()
    blocks = []
    for offset in range(-1, HORIZON.days + 1):
        day = today + timedelta(days=offset)
        for entry in week.get(WEEKDAYS[day.weekday()]) or []:
            start, end = _time(entry.get("from")), _time(entry.get("to"))
            if start is None or end is None:
                continue
            ends = (
                datetime.combine(day + timedelta(days=1), time(0), zone)
                if end == time.max  # 24:00
                else datetime.combine(day, end, zone)
            )
            data = entry.get("data") or {}
            blocks.append(
                Block(
                    dt_util.as_utc(datetime.combine(day, start, zone)),
                    dt_util.as_utc(ends),
                    _float(data.get("temperature")),
                )
            )
    return sorted(blocks, key=lambda block: block.start)


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
        *,
        on_manual_change: Callable[[str], None] | None = None,
    ) -> None:
        """Read the room's configuration and its stored state."""
        self.hass = hass
        self._on_manual_change = on_manual_change
        self.entry = entry
        self.room_id = subentry.subentry_id
        self.name = subentry.title
        data = subentry.data
        self.thermostats: list[str] = list(data[CONF_THERMOSTATS])
        self.schedule: str = data[CONF_SCHEDULE]
        self.windows: list[str] = list(data.get(CONF_WINDOWS, []))
        self.room_sensor: str | None = data.get(CONF_ROOM_SENSOR)
        # Per thermostat an optional entity that says how much it heats (% or on/off).
        self.demand: dict[str, str] = {
            trv: entity
            for trv, entity in data.get(CONF_DEMAND, {}).items()
            if trv in self.thermostats
        }
        self.demand_threshold = float(
            entry.options.get(CONF_DEMAND_THRESHOLD, DEFAULT_DEMAND_THRESHOLD)
        )
        window = data.get(SECTION_WINDOW, {})
        reminder = entry.options.get(SECTION_REMINDER, {})
        # Minutes after which an open window is reminded of; 0 (or no windows): never.
        remind_minutes = (
            int(window.get(CONF_REMIND_AFTER, DEFAULT_REMIND_AFTER_MINUTES) or 0)
            if self.windows
            else 0
        )
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
            remind_after=timedelta(minutes=remind_minutes) if remind_minutes else None,
            remind_below=_float(reminder.get(CONF_ONLY_BELOW)),
        )
        self.remind_minutes = remind_minutes
        self.outdoor_sensor: str | None = (
            reminder.get(CONF_OUTDOOR_SENSOR) if self.windows else None
        )
        self.notify_targets: list[str] = list(reminder.get(CONF_NOTIFY, []))
        self.idle_sensors: list[str] = list(entry.options.get(CONF_IDLE_SENSORS, []))
        self._store = store
        self._stored: RoomDict = store.room(self.room_id)
        self.state: RoomState = state_from_dict(self._stored.get("state"))
        self.inputs: Inputs | None = None
        self.desired: Desired | None = None
        # The schedule's weekly blocks (from schedule.get_schedule), and what they make of the room.
        self._week: Mapping[str, Any] | None = None
        self.forecast: Forecast | None = None
        self._forecast_key: tuple[Any, ...] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._wakeup: CALLBACK_TYPE | None = None
        self._external_timer: CALLBACK_TYPE | None = None
        # A change made outside the integration, waiting for the dial to settle: which thermostat.
        self._pending_external: tuple[str, ExternalChange] | None = None
        self._views: dict[str, TrvView] = {}
        # Last available state of each input: an unavailable one keeps its last known state.
        self._known: dict[str, State] = {}
        self._starting = False
        self._issues: dict[str, dict[str, str]] = {}  # raised issues and their placeholders
        self._contact_timers: dict[str, CALLBACK_TYPE] = {}
        self.trace: deque[dict[str, Any]] = deque(maxlen=TRACE_LENGTH)
        self.counters: Counter[str] = Counter()
        self.writers = {
            eid: TrvWriter(
                hass,
                entry,
                eid,
                self.name,
                trace=self._trace,
                counters=self.counters,
                on_send=self._remember_command,
            )
            for eid in self.thermostats
        }

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

    def demand_value(self, thermostat: str) -> float | bool | None:
        """Return the thermostat's demand: a number, on/off, or None when unknown."""
        entity_id = self.demand.get(thermostat)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if state.domain == "binary_sensor":
            return state.state == STATE_ON
        return _float(state.state)

    def status(self, thermostat: str) -> Status | None:
        """Return whether the thermostat heats; None when that is not known."""
        view = self._view(thermostat)
        mode = view.hvac_mode if view.available else None
        return heating_status(
            mode, demand=self.demand_value(thermostat), threshold=self.demand_threshold
        )

    @property
    def off_schedule(self) -> bool:
        """Whether something other than the plan decides: what "resume" would end."""
        return self.state.override is not None or self.state.boost is not None

    @property
    def action(self) -> Status | None:
        """The room's status: off, heating if any thermostat heats, reached if all are known."""
        return room_action([self.status(eid) for eid in self.thermostats])

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
    def boost(self, temperature: float | None = None, duration: timedelta | None = None) -> None:
        """Heat hard for a while; without arguments as the house settings say."""
        options = self.entry.options.get(SECTION_BOOST, {})
        if temperature is None:
            temperature = float(options.get(CONF_BOOST_TEMPERATURE, DEFAULT_BOOST_TEMPERATURE))
        if duration is None:
            duration = _duration(
                options.get(CONF_BOOST_DURATION), timedelta(minutes=DEFAULT_BOOST_MINUTES)
            )
        self._run(StartBoost(temperature, dt_util.utcnow() + duration))

    @callback
    def set_override(
        self, temperature: float, until: datetime | None = None, preset: str | None = None
    ) -> None:
        """Heat at `temperature` until `until` (UTC), or until the next plan change."""
        self._run(SetOverride(temperature, until, preset))

    @callback
    def extend_block(self, until: datetime) -> None:
        """Keep the plan's current temperature until `until` (UTC)."""
        self._run(ExtendBlock(until))

    @callback
    def end_preset(self) -> None:
        """End a boost and a preset's hold."""
        self._run(EndPreset())

    @property
    def preset(self) -> str:
        """The room thermostat's preset: boost, comfort or eco, else none."""
        if self.state.boost is not None:
            return "boost"
        override = self.state.override
        return override.preset if override is not None and override.preset else "none"

    @callback
    def set_number(self, key: str, value: float) -> None:
        """Change the heating or idle temperature; a real change ends a manual hold."""
        if key == "heating_temperature":
            if self._stored["heating_temperature"] == value:
                return
            self._stored["heating_temperature"] = value
        else:
            if self._stored["idle_temperature"] == value:
                return
            self._stored["idle_temperature"] = value
        self._store.save()
        self._run(NumberChanged())

    def diagnostics(self) -> dict[str, Any]:
        """Everything that explains the room's behaviour, for a bug report."""
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
            "writers": {eid: writer.diagnostics() for eid, writer in self.writers.items()},
            "pending_external": {
                "thermostat": self._pending_external[0],
                **asdict(self._pending_external[1]),
            }
            if self._pending_external
            else None,
            "heating": {
                eid: {
                    "demand_entity": self.demand.get(eid),
                    "demand": self.demand_value(eid),
                    "status": self.status(eid),
                }
                for eid in self.thermostats
            },
            "demand_threshold": self.demand_threshold,
            "counters": dict(self.counters),
            "trace": list(self.trace),
        }

    def _trace(self, what: str, **details: Any) -> None:
        self.trace.append({"at": dt_util.utcnow().isoformat(), "what": what, **details})

    # --- lifecycle ---

    async def async_start(self) -> None:
        """Snapshot the thermostats, follow every input, decide."""
        self._views = {eid: self._view(eid) for eid in self.thermostats}
        await self._async_fetch_week()
        self._starting = True
        self._unsubs.append(async_call_later(self.hass, START_GRACE, self._on_start_grace_over))
        inputs = [self.schedule, *self.idle_sensors, *self.windows]
        inputs += [e for e in (self.room_sensor, self.outdoor_sensor) if e]
        self._unsubs.append(async_track_state_change_event(self.hass, inputs, self._on_input))
        # A renamed, removed or disabled entity of the room: a repair issue.
        self._unsubs.append(
            self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry_updated)
        )
        # Editing a schedule may change nothing in its state: only a report tells.
        self._unsubs.append(
            async_track_state_report_event(self.hass, [self.schedule], self._on_schedule_reported)
        )
        self._unsubs.append(
            async_track_state_change_event(self.hass, self.thermostats, self._on_thermostat)
        )
        if self.demand:
            # A demand changes only the heating status, not what the room should do.
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, list(self.demand.values()), self._on_demand
                )
            )
        # Changes made while Home Assistant was down are no sign of the tado° app overwriting
        # setpoints now: they all show up in the same second. Not reported to the house.
        self._run(self._changed_while_down())
        # From now on a restart compares against what the thermostats have now, also those the
        # integration never had to write.
        for entity_id, view in self._views.items():
            if view.available:
                self._remember(entity_id, view)

    @callback
    def async_stop(self) -> None:
        """Stop following and cancel timers and writes."""
        for unsub in (*self._unsubs, self._wakeup, self._external_timer):
            if unsub is not None:
                unsub()
        self._unsubs.clear()
        self._wakeup = self._external_timer = None
        for writer in self.writers.values():
            writer.stop()
        for cancel in self._contact_timers.values():
            cancel()
        self._contact_timers.clear()
        for issue_id in list(self._issues):
            self._set_issue(issue_id, active=False)

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
        # Shortly after a start, inputs not known yet keep the last decision (the stored plan key
        # and window phase), so a sensor slow to come up neither switches the plan, ends holds,
        # nor lets a room heat with its window open. Later, an unknown input counts as off.
        last = self.state.plan_key if self._starting else None
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
        window_states = [self._known_state(e) for e in self.windows]
        window_open = any(s is not None and s.state == STATE_ON for s in window_states)
        if not window_open and self._starting and None in window_states:
            window_open = self.state.window in (WindowPhase.OPENING, WindowPhase.OPEN)
        return Inputs(
            schedule_on=schedule_on,
            block_temperature=block,
            idle=idle,
            heating_temperature=self.heating_temperature,
            idle_temperature=self.idle_temperature,
            window_open=window_open,
            room_temperature=self._room_temperature(),
            outdoor_temperature=self._outdoor_temperature(),
        )

    def _outdoor_temperature(self) -> float | None:
        if not self.outdoor_sensor:
            return None
        state = self._known_state(self.outdoor_sensor)
        return _float(state.state) if state else None

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
    def _on_input(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        if entity_id == self.schedule:
            self._refresh_week()
        self._run(plan_edge=entity_id == self.schedule or entity_id in self.idle_sensors)

    @callback
    def _on_schedule_reported(self, _event: Event[EventStateReportedData]) -> None:
        self._refresh_week()

    @callback
    def _refresh_week(self) -> None:
        async def refresh() -> None:
            await self._async_fetch_week()
            self._update_forecast()
            self._notify()

        self.entry.async_create_background_task(
            self.hass, refresh(), f"tado_x_matter_pro schedule {self.name}"
        )

    async def _async_fetch_week(self) -> None:
        """Read the schedule's blocks; without them only deadlines are forecast."""
        try:
            response = await self.hass.services.async_call(
                "schedule",
                "get_schedule",
                {"entity_id": self.schedule},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError:
            self._week = None
            return
        week = response.get(self.schedule) if response else None
        self._week = week if isinstance(week, Mapping) else None

    @callback
    def _on_start_grace_over(self, _now: datetime) -> None:
        self._starting = False
        self._run()

    @callback
    def _on_demand(self, _event: Event[EventStateChangedData]) -> None:
        self._notify()

    @callback
    def _on_thermostat(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        old = self._views.get(entity_id)
        new = self._view(entity_id)
        self._views[entity_id] = new
        desired = (
            (self.desired.hvac_mode, self.desired.temperature) if self.desired else ("heat", None)
        )
        writer = self.writers[entity_id]
        known = self._stored["last_known"].get(entity_id)
        report = classify(
            old,
            new,
            desired=desired,
            command=writer.command,
            context_id=new_state.context.id if new_state else None,
            now=dt_util.utcnow(),
            known=(known[0], known[1]) if known else None,
            recent=self._recent_for(entity_id, old),
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
        if new.available and report is not Report.INTERMEDIATE:
            self._remember(entity_id, new)  # what it settled on, by whomever
        if new.available and report is not Report.EXTERNAL:
            # A late delivery of an older write, or a thermostat back from a drop-out: send again.
            writer.observe(new, resend=report in (Report.STALE, Report.RECONNECTED))
        if report is Report.EXTERNAL:
            _LOGGER.debug("%s: %s changed externally to %s", self.name, entity_id, new)
            self._pending_external = (
                entity_id,
                ExternalChange(new.hvac_mode or "off", new.setpoint),
            )
            if self._external_timer is not None:
                self._external_timer()
            self._external_timer = async_call_later(
                self.hass, EXTERNAL_COALESCE, self._fire_external
            )
            self._notify()  # the thermostat's heating status may have changed
            return
        pending = self._pending_external
        if pending is not None and pending[0] == entity_id and matches(new, desired):
            # The rest of a late delivery: the thermostat ends where the room wants it, so the
            # report before was a step on the way, not someone's change.
            self._cancel_pending_external("settled where wanted")
        # Readings changed, or a thermostat came back: decide again.
        self._run()

    def _recent_for(
        self, entity_id: str, old: TrvView | None
    ) -> list[tuple[str | None, float | None]]:
        """Values sent lately that may still be delivered late.

        Back from a drop-out, the last command stored before a restart counts too: the writer's
        own memory of it is gone with the restart.
        """
        recent = list(self.writers[entity_id].recent())
        sent = self._stored.get("last_commanded", {}).get(entity_id)
        if sent and (old is None or not old.available):
            recent.append((sent[0], sent[1]))
        return recent

    def _cancel_pending_external(self, why: str) -> None:
        if self._pending_external is not None:
            self._trace("external_dropped", thermostat=self._pending_external[0], why=why)
        self._pending_external = None
        if self._external_timer is not None:
            self._external_timer()
            self._external_timer = None

    @callback
    def _fire_external(self, _now: datetime) -> None:
        self._external_timer = None
        pending, self._pending_external = self._pending_external, None
        if pending is None:
            return
        entity_id, change = pending
        desired = self.desired
        if desired is not None and matches(
            self._view(entity_id), (desired.hvac_mode, desired.temperature)
        ):
            # Meanwhile it shows what the room wants: no change to hold.
            self._trace("external_dropped", thermostat=entity_id, why="shows what is wanted")
            self._run()
            return
        self._run(self._manual(change))

    def _manual(self, change: ExternalChange | None) -> ExternalChange | None:
        """Tell the house about a change made outside the integration; pass it on."""
        if change is not None and self._on_manual_change is not None:
            self._on_manual_change(self.name)
        return change

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _remember(self, entity_id: str, view: TrvView) -> None:
        known = [view.hvac_mode, view.setpoint]
        if self._stored["last_known"].get(entity_id) != known:
            self._stored["last_known"][entity_id] = known
            self._store.save()

    def _remember_command(self, entity_id: str, want: tuple[str, float | None]) -> None:
        commanded = self._stored.setdefault("last_commanded", {})
        if commanded.get(entity_id) != list(want):
            commanded[entity_id] = list(want)
            self._store.save()

    def _changed_while_down(self) -> ExternalChange | None:
        """Return a change made while HA was down: a thermostat differs from what we knew.

        What the integration sent last counts as known too: a write still on its way when Home
        Assistant stopped arrives while it is down.
        """
        commanded = self._stored.get("last_commanded", {})
        for entity_id, view in self._views.items():
            known = self._stored["last_known"].get(entity_id)
            if not known or not view.available:
                continue
            sent = commanded.get(entity_id)
            if sent and matches(view, (sent[0], sent[1])):
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
    def _run(self, event: RoomEvent | None = None, *, plan_edge: bool = False) -> None:
        previous_key = self.state.plan_key
        before = self.state
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
        self._log(before, isinstance(event, Resume))
        self._update_forecast()
        self._check_issues()
        # Most runs are readings that change nothing: write to disk only when the state changed.
        stored = state_to_dict(self.state)
        if stored != self._stored.get("state"):
            self._stored["state"] = stored
            self._store.save()
        self._schedule_wakeup(result.next_wakeup)
        self._notify()
        spread = plan_edge and previous_key is not None and self.state.plan_key != previous_key
        self._deliver(random_delay() if spread else timedelta(0))

    def _check_issues(self) -> None:
        """Raise or clear the room's repair issues.

        Bouncing contacts, contacts gone while open, and – once integrations had time to load –
        entities of the room that are gone (renamed, deleted or disabled).
        """
        missing = (
            []
            if self._starting
            else [e for e in self._room_inputs() if entity_missing(self.hass, e)]
        )
        self._set_issue(
            f"missing_{self.room_id}",
            active=bool(missing),
            key="inputs_missing",
            room=self.name,
            entities=", ".join(missing),
        )
        bounces = len(self.state.bounces)
        self._set_issue(
            f"chatter_{self.room_id}",
            active=bounces >= CHATTER_BOUNCES,
            key="window_chatter",
            room=self.name,
            count=str(bounces),
        )
        for entity_id in self.windows:
            state = self.hass.states.get(entity_id)
            gone = state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)
            known = self._known.get(entity_id)
            last_open = (
                known.state == STATE_ON
                if known is not None
                else (self.state.window in (WindowPhase.OPENING, WindowPhase.OPEN))
            )
            issue_id = f"contact_{entity_id}"
            if gone and last_open:
                if entity_id not in self._contact_timers and issue_id not in self._issues:
                    self._contact_timers[entity_id] = async_call_later(
                        self.hass, CONTACT_ISSUE_AFTER, partial(self._contact_gone, entity_id)
                    )
            else:
                if (cancel := self._contact_timers.pop(entity_id, None)) is not None:
                    cancel()
                self._set_issue(issue_id, active=False)

    def _room_inputs(self) -> list[str]:
        """Return every entity the room's settings name."""
        extra = [e for e in (self.room_sensor,) if e]
        return [*self.thermostats, self.schedule, *self.windows, *extra, *self.demand.values()]

    @callback
    def _on_registry_updated(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        ids = {event.data["entity_id"], event.data.get("old_entity_id")}
        if not self._starting and ids & set(self._room_inputs()):
            self._check_issues()

    @callback
    def _contact_gone(self, entity_id: str, _now: datetime) -> None:
        self._contact_timers.pop(entity_id, None)
        self._set_issue(
            f"contact_{entity_id}",
            active=True,
            key="window_contact_unavailable",
            room=self.name,
            contact=entity_id,
        )

    def _set_issue(
        self, issue_id: str, *, active: bool, key: str = "", **placeholders: str
    ) -> None:
        if active and self._issues.get(issue_id) != placeholders:  # new, or its text changed
            self._issues[issue_id] = placeholders
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders=placeholders,
            )
        elif not active and issue_id in self._issues:
            del self._issues[issue_id]
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def _update_forecast(self) -> None:
        """Work out the next change, unless nothing it depends on changed."""
        if self.inputs is None or self.desired is None:
            return
        now = dt_util.utcnow()
        # Readings alone hardly change the forecast; leave them out of what triggers it.
        key = (
            self._stored.get("state"),
            replace(self.inputs, room_temperature=None),
            self.desired,
            id(self._week),
        )
        if key == self._forecast_key and (self.forecast is None or self.forecast.at > now):
            return
        self._forecast_key = key
        blocks = expand_week(self._week, now) if self._week else []
        self.forecast = forecast(
            self.state, self.inputs, self.config, now, desired=self.desired, blocks=blocks
        )

    def _log(self, before: RoomState, resumed: bool) -> None:  # noqa: FBT001
        """Fire an event for each logbook entry the step made (logbook.py words them)."""
        found = log_entries(before, self.state, resumed=resumed)
        if not found:
            return
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "climate", DOMAIN, f"{self.room_id}_climate"
        )
        for entry in found:
            if entry.kind is Kind.WINDOW_REMINDER:
                self._send_reminder()
            self.hass.bus.async_fire(
                EVENT_ROOM,
                {
                    "room": self.name,
                    "entity_id": entity_id,
                    "kind": entry.kind,
                    "temperature": entry.temperature,
                    "until": entry.until.isoformat() if entry.until else None,
                },
            )

    def _send_reminder(self) -> None:
        """Tell the house's notify targets that a window has been open too long."""
        title, text = reminder(self.hass.config.language, self.name, self.remind_minutes)
        for target in self.notify_targets:
            domain, _, service = target.partition(".")
            if domain != "notify" or not service:
                _LOGGER.warning("%s: %s is not a notify action", self.name, target)
                continue
            self.entry.async_create_background_task(
                self.hass,
                self._async_notify(service, title, text),
                f"tado_x_matter_pro reminder {self.name}",
            )

    async def _async_notify(self, service: str, title: str, text: str) -> None:
        try:
            await self.hass.services.async_call(
                "notify", service, {"title": title, "message": text}, blocking=True
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "%s: the window reminder via notify.%s failed: %s", self.name, service, err
            )

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

    def _deliver(self, delay: timedelta) -> None:
        """Hand the decision to each thermostat's writer; they send only what deviates."""
        desired = self.desired
        if desired is None or self._pending_external is not None:
            # While a dial turn settles, the old target would turn it back; it becomes the hold.
            return
        for writer in self.writers.values():
            writer.want((desired.hvac_mode, desired.temperature), delay)
