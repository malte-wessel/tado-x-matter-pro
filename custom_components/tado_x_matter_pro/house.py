"""What concerns all rooms: noticing that something else overwrites setpoints in several rooms."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import DOMAIN

# Manual changes in this many rooms within this time are rarely people: likely the tado° app's own
# schedule or settings overwriting the setpoints.
OVERWRITE_ROOMS = 2
OVERWRITE_WITHIN = timedelta(seconds=60)
ISSUE_OVERWRITING = "tado_overwriting"


class House:
    """The house-wide watcher; rooms report their manual changes to it."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Start with nothing seen."""
        self.hass = hass
        self._seen: dict[str, datetime] = {}

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
