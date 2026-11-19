"""What concerns all rooms: setpoints overwritten in several rooms, missing house inputs."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_IDLE_SENSORS,
    CONF_OUTDOOR_SENSOR,
    DOMAIN,
    SECTION_REMINDER,
    START_GRACE,
)

# Manual changes in this many rooms within this time are not people walking from dial to dial:
# likely the tado° app's own schedule or settings overwriting the setpoints at once.
OVERWRITE_ROOMS = 2
OVERWRITE_WITHIN = timedelta(seconds=10)
ISSUE_OVERWRITING = "tado_overwriting"
ISSUE_HOUSE_MISSING = "house_inputs_missing"


def entity_missing(hass: HomeAssistant, entity_id: str) -> bool:
    """Return whether an entity is gone: no state and not registered, or disabled.

    A renamed or deleted entity looks like this; an unavailable one does not.
    """
    if hass.states.get(entity_id) is not None:
        return False
    entry = er.async_get(hass).async_get(entity_id)
    return entry is None or entry.disabled_by is not None


class House:
    """The house-wide watcher; rooms report their manual changes to it."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Start with nothing seen."""
        self.hass = hass
        reminder = entry.options.get(SECTION_REMINDER, {})
        outdoor = reminder.get(CONF_OUTDOOR_SENSOR)
        self.inputs: list[str] = [
            *entry.options.get(CONF_IDLE_SENSORS, []),
            *([outdoor] if outdoor else []),
        ]
        self._seen: dict[str, datetime] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._missing = False

    @callback
    def async_start(self) -> None:
        """Check the house settings' entities once integrations have loaded, and on changes."""
        self._unsubs.append(async_call_later(self.hass, START_GRACE, self._on_grace_over))

    @callback
    def async_stop(self) -> None:
        """Stop following; drop the house's missing-inputs issue."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._missing:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_HOUSE_MISSING)
            self._missing = False

    @callback
    def _on_grace_over(self, _now: datetime) -> None:
        self._unsubs.append(
            self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_registry)
        )
        if self.inputs:
            self._unsubs.append(
                async_track_state_change_event(self.hass, self.inputs, self._on_state)
            )
        self._check()

    @callback
    def _on_registry(self, _event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        self._check()

    @callback
    def _on_state(self, _event: Event[EventStateChangedData]) -> None:
        self._check()

    def _check(self) -> None:
        missing = [e for e in self.inputs if entity_missing(self.hass, e)]
        if missing:
            self._missing = True
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_HOUSE_MISSING,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_HOUSE_MISSING,
                translation_placeholders={"entities": ", ".join(missing)},
            )
        elif self._missing:
            self._missing = False
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_HOUSE_MISSING)

    @callback
    def note_manual_change(self, room: str) -> None:
        """Note that a room took a change made outside the integration as a manual change."""
        now = dt_util.utcnow()
        self._seen = {r: at for r, at in self._seen.items() if now - at <= OVERWRITE_WITHIN}
        self._seen[room] = now
        if len(self._seen) >= OVERWRITE_ROOMS:
            # Not persistent: it goes with the next restart, and comes back if it happens again.
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_OVERWRITING,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_OVERWRITING,
                translation_placeholders={"rooms": ", ".join(sorted(self._seen))},
            )
