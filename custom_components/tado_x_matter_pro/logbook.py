"""Logbook entries of the rooms, worded in Home Assistant's language when they are shown."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook.const import (
    LOGBOOK_ENTRY_CONTEXT_ID,
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.components.logbook.models import LazyEventPartialState
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, EVENT_ROOM
from .messages import message


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[
        [str, str, Callable[[LazyEventPartialState], dict[str, Any]]], None
    ],
) -> None:
    """Describe the rooms' events."""

    @callback
    def describe(event: LazyEventPartialState) -> dict[str, Any]:
        data = event.data
        until = dt_util.parse_datetime(data["until"]) if data.get("until") else None
        return {
            LOGBOOK_ENTRY_NAME: data.get("room"),
            LOGBOOK_ENTRY_MESSAGE: message(
                hass.config.language, data["kind"], data.get("temperature"), until
            ),
            LOGBOOK_ENTRY_ENTITY_ID: data.get("entity_id"),
            LOGBOOK_ENTRY_CONTEXT_ID: event.context_id,
        }

    async_describe_event(DOMAIN, EVENT_ROOM, describe)
