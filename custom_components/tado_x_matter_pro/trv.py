"""One thermostat's writes: deliver what the room wants, confirm it, retry; never block the room.

Thread links drop out, and the Matter server may hold a write for minutes. So every write is
checked: unless the thermostat reports the wanted value, it is sent again on a fixed schedule.
Home Assistant drops calls to an unavailable entity, so nothing is sent while the thermostat is
unavailable; when it comes back, the room re-applies. Each thermostat has its own writer, so one
that does not answer never delays its siblings or other rooms.
"""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .engine.external import Command, Setting, TrvView, matches

_LOGGER = logging.getLogger(__name__)

# When to send a write that is not confirmed yet, counted from the first attempt.
RETRY_HEAT = (timedelta(0), timedelta(minutes=1), timedelta(minutes=3), timedelta(minutes=10))
RETRY_OFF = (timedelta(0), timedelta(seconds=30), timedelta(minutes=2))
CONFIRM_WITHIN = timedelta(seconds=60)  # after the last attempt, then the writer gives up
CALL_TIMEOUT = 30  # seconds a service call may take before it counts as failed
# After giving up, a report that still deviates sends again, at most this often.
REAPPLY_AFTER = timedelta(minutes=10)
# Values commanded lately: a late delivery of one of them is ours, not a manual change.
RECENT = timedelta(minutes=20)
RECENT_MAX = 5
UNCONFIRMED_ISSUE_AFTER = timedelta(minutes=30)

type Want = tuple[str, float | None]


class Phase(StrEnum):
    """Where a writer is with its current desired setting."""

    CONFIRMED = "confirmed"  # the thermostat shows it
    PENDING = "pending"  # attempts are scheduled
    GAVE_UP = "gave_up"  # all attempts are used; a reconnect or a deviating report sends again


class TrvWriter:
    """Delivers the desired mode and setpoint to one thermostat."""

    def __init__(  # noqa: PLR0913 – the room hands over its pieces
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        entity_id: str,
        room: str,
        *,
        trace: Callable[..., None],
        counters: Counter[str],
    ) -> None:
        """Start without a desired setting; the room's first decision sets it."""
        self.hass = hass
        self.entry = entry
        self.entity_id = entity_id
        self.room = room
        self._trace = trace
        self._counters = counters
        self.desired: Want | None = None
        self.phase = Phase.CONFIRMED
        self.command: Command | None = None
        self._recent: deque[tuple[Want, datetime]] = deque(maxlen=RECENT_MAX)
        self._attempt = 0
        self._first_attempt: datetime | None = None
        self._last_attempt: datetime | None = None
        self.unconfirmed_since: datetime | None = None
        self._timer: CALLBACK_TYPE | None = None
        self._issue_timer: CALLBACK_TYPE | None = None
        self._issue = False
        self._task: asyncio.Task[None] | None = None
        self._again = False
        self.stats: Counter[str] = Counter()

    # --- what the room calls ---

    @callback
    def want(self, setting: Want, delay: timedelta = timedelta(0)) -> None:
        """Make `setting` the desired one; send it unless the thermostat already shows it."""
        view = self._view()
        if setting != self.desired:
            if self.command is not None and self.command.want == self.desired:
                self._recent.append((self.command.want, dt_util.utcnow()))  # it was sent
            self.desired = setting
            self.command = None
            if matches(view, setting):
                self._confirm()
            else:
                self._start(delay)
            return
        if matches(view, setting):
            self._confirm()
        elif self.phase is Phase.CONFIRMED:
            self._start()  # it drifted away from a value it had confirmed
        elif self.phase is Phase.GAVE_UP and self._may_reapply():
            self._start()

    @callback
    def observe(self, view: TrvView, *, resend: bool) -> None:
        """Take a report of the thermostat; `resend` after a stale delivery or a reconnect."""
        if self.desired is None:
            return
        if matches(view, self.desired):
            self._confirm()
        elif resend:
            self._start()

    def recent(self) -> list[Setting]:
        """Return values commanded lately other than the desired one."""
        since = dt_util.utcnow() - RECENT
        return [want for want, at in self._recent if at >= since and want != self.desired]

    @callback
    def stop(self) -> None:
        """Cancel timers and the call in flight; drop the repair issue."""
        self._cancel_timer()
        self._cancel_issue_timer()
        if self._task is not None:
            self._task.cancel()
        self._delete_issue()

    def diagnostics(self) -> dict[str, Any]:
        """Return the writer's state, for a bug report."""
        command = self.command
        return {
            "desired": list(self.desired) if self.desired else None,
            "phase": self.phase,
            "attempt": self._attempt,
            "first_attempt": self._first_attempt,
            "last_attempt": self._last_attempt,
            "unconfirmed_since": self.unconfirmed_since,
            "recent": [[list(want), at] for want, at in self._recent],
            "command": None
            if command is None
            else {
                "prev": list(command.prev),
                "want": list(command.want),
                "issued_at": command.issued_at,
                "returned_at": command.returned_at,
                "confirmed": command.confirmed,
                "context_ids": sorted(command.context_ids),
            },
            "stats": dict(self.stats),
        }

    # --- the schedule ---

    def _schedule(self) -> tuple[timedelta, ...]:
        return RETRY_OFF if self.desired and self.desired[0] == "off" else RETRY_HEAT

    def _may_reapply(self) -> bool:
        last = self._last_attempt
        return last is None or dt_util.utcnow() - last >= REAPPLY_AFTER

    def _start(self, delay: timedelta = timedelta(0)) -> None:
        """Begin a new round of attempts, the first after `delay`."""
        self._cancel_timer()
        self.phase = Phase.PENDING
        self._attempt = 0
        now = dt_util.utcnow()
        self._first_attempt = now + delay
        if self.unconfirmed_since is None:
            self.unconfirmed_since = now
            self._issue_timer = async_track_point_in_utc_time(
                self.hass, self._on_unconfirmed_too_long, now + UNCONFIRMED_ISSUE_AFTER
            )
        if delay > timedelta(0):
            self._trace("delayed", thermostat=self.entity_id, seconds=round(delay.total_seconds()))
            self._timer = async_track_point_in_utc_time(
                self.hass, self._on_timer, self._first_attempt
            )
            self._attempt = -1  # the timer makes it attempt 0
            return
        self._send()
        if self.phase is Phase.PENDING:
            self._arm()

    def _arm(self) -> None:
        """Wait for the next attempt, or – after the last one – for its confirmation."""
        schedule = self._schedule()
        first = self._first_attempt or dt_util.utcnow()
        if self._attempt + 1 < len(schedule):
            when = first + schedule[self._attempt + 1]
        else:
            when = (self._last_attempt or dt_util.utcnow()) + CONFIRM_WITHIN
        self._timer = async_track_point_in_utc_time(self.hass, self._on_timer, when)

    @callback
    def _on_timer(self, _now: datetime) -> None:
        self._timer = None
        if self.phase is not Phase.PENDING:
            return
        self._attempt += 1
        if self._attempt >= len(self._schedule()):
            self.phase = Phase.GAVE_UP
            self._counters["gave_up"] += 1
            self.stats["gave_up"] += 1
            self._trace("gave_up", thermostat=self.entity_id, want=list(self.desired or ()))
            _LOGGER.warning(
                "%s: %s did not confirm %s after %d attempts",
                self.room,
                self.entity_id,
                self.desired,
                len(self._schedule()),
            )
            return
        if self._attempt > 0:
            self._counters["retry"] += 1
            self.stats["retries"] += 1
            self._trace("retry", thermostat=self.entity_id, attempt=self._attempt)
        self._send()
        if self.phase is Phase.PENDING:
            self._arm()

    def _confirm(self) -> None:
        was_pending = self.phase is not Phase.CONFIRMED
        self._cancel_timer()
        self._cancel_issue_timer()
        self.phase = Phase.CONFIRMED
        self.unconfirmed_since = None
        if self.command is not None:
            self.command.confirmed = True
        if was_pending:
            self._counters["confirmed"] += 1
            self.stats["confirmed"] += 1
            self._trace("confirmed", thermostat=self.entity_id, want=list(self.desired or ()))
        self._delete_issue()

    # --- sending ---

    def _view(self) -> TrvView:
        state = self.hass.states.get(self.entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return TrvView(available=False)
        setpoint = state.attributes.get("temperature")
        return TrvView(
            available=True,
            hvac_mode=state.state,
            setpoint=float(setpoint) if isinstance(setpoint, int | float) else None,
        )

    def _send(self) -> None:
        """Send the desired setting now, unless a call is still on its way."""
        want = self.desired
        view = self._view()
        if want is None:
            return
        if matches(view, want):
            self._confirm()
            return
        if not view.available:
            self._trace("unavailable", thermostat=self.entity_id, attempt=self._attempt)
            return  # Home Assistant would drop the call; a reconnect sends again
        if self._task is not None and not self._task.done():
            self._again = True  # one call at a time; the latest desired goes next
            return
        now = dt_util.utcnow()
        context = Context()
        if self.command is None or self.command.want != want:
            self.command = Command(prev=(view.hvac_mode, view.setpoint), want=want, issued_at=now)
        self.command.context_ids.add(context.id)
        self.command.issued_at = now
        self.command.returned_at = None
        self._last_attempt = now
        self._counters["write"] += 1
        self.stats["attempts"] += 1
        self._trace(
            "write",
            thermostat=self.entity_id,
            want=list(want),
            attempt=self._attempt,
            context_id=context.id,
        )
        self._task = self.entry.async_create_background_task(
            self.hass, self._async_call(want, context), f"tado_x_matter_pro write {self.entity_id}"
        )

    async def _async_call(self, want: Want, context: Context) -> None:
        data: dict[str, Any]
        if want[0] == "off":
            service, data = "set_hvac_mode", {"hvac_mode": "off"}
        else:
            service, data = "set_temperature", {"temperature": want[1], "hvac_mode": "heat"}
        try:
            async with asyncio.timeout(CALL_TIMEOUT):
                await self.hass.services.async_call(
                    "climate",
                    service,
                    {"entity_id": self.entity_id, **data},
                    blocking=True,
                    context=context,
                )
        except TimeoutError:
            self._counters["write_timeout"] += 1
            self._trace("write_timeout", thermostat=self.entity_id)
        except HomeAssistantError as err:
            _LOGGER.warning("%s: writing %s failed: %s", self.room, self.entity_id, err)
            self._counters["write_failed"] += 1
            self._trace("write_failed", thermostat=self.entity_id, error=str(err))
        finally:
            if self.command is not None and self.command.want == want:
                self.command.returned_at = dt_util.utcnow()
            if self._again:
                self._again = False
                self.hass.loop.call_soon(self._send)

    # --- the repair issue ---

    @callback
    def _on_unconfirmed_too_long(self, _now: datetime) -> None:
        self._issue_timer = None
        if self.phase is Phase.CONFIRMED:
            return
        self._issue = True
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="thermostat_unconfirmed",
            translation_placeholders={"thermostat": self._name(), "room": self.room},
        )

    @property
    def _issue_id(self) -> str:
        return f"unconfirmed_{self.entity_id}"

    def _delete_issue(self) -> None:
        if self._issue:
            self._issue = False
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)

    def _name(self) -> str:
        state = self.hass.states.get(self.entity_id)
        return state.name if state else self.entity_id

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    def _cancel_issue_timer(self) -> None:
        if self._issue_timer is not None:
            self._issue_timer()
            self._issue_timer = None
