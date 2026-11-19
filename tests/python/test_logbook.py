"""Logbook entries: fired for holds, resume, windows and boost; worded in English or German."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Event, HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.tado_x_matter_pro import logbook
from custom_components.tado_x_matter_pro.const import DOMAIN, EVENT_ROOM
from custom_components.tado_x_matter_pro.messages import message
from tests.python.conftest import FakeTrv, set_inputs

type Setup = Callable[..., Awaitable[MockConfigEntry]]


async def test_a_rooms_day_in_the_logbook(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    fired: list[dict[str, Any]] = []
    hass.bus.async_listen(EVENT_ROOM, lambda event: fired.append(dict(event.data)))

    async def advance(seconds: float) -> None:
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()

    trvs["climate.kitchen_trv"].dial(23.0)
    await advance(4)
    set_inputs(hass, kitchen_window="on")
    await advance(30)
    set_inputs(hass, kitchen_window="off")
    await advance(5 * 60)
    await hass.services.async_call(
        DOMAIN, "boost", {"entity_id": "climate.kitchen_heating"}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "resume_schedule", {"entity_id": "climate.kitchen_heating"}, blocking=True
    )
    await hass.async_block_till_done()

    kitchen = [e for e in fired if e["room"] == "Kitchen"]
    assert [e["kind"] for e in kitchen] == ["hold", "window_off", "window_on", "boost", "resumed"]
    assert kitchen[0]["temperature"] == 23.0
    assert {e["entity_id"] for e in kitchen} == {"climate.kitchen_heating"}


def test_the_texts_in_english_and_german() -> None:
    until = datetime(2026, 11, 19, 13, 30, tzinfo=UTC)
    local = dt_util.as_local(until).strftime("%H:%M")
    assert message("en", "hold", 21.5) == "holds 21.5 °C until the next schedule change"
    assert message("de", "hold", 21.5) == "hält 21,5 °C bis zur nächsten Zeitplanänderung"
    assert message("de-CH", "boost", 30.0, until) == f"Boost auf 30 °C bis {local}"
    assert message("fr", "window_off") == "switched off: a window is open"


async def test_the_logbook_describes_the_events_in_the_language_of_home_assistant(
    hass: HomeAssistant,
) -> None:
    described: dict[str, Callable[[Any], dict[str, Any]]] = {}
    logbook.async_describe_events(
        hass, lambda _domain, event_type, describe: described.update({event_type: describe})
    )
    hass.config.language = "de"
    event = Event(
        EVENT_ROOM,
        {"room": "Küche", "entity_id": "climate.kitchen_heating", "kind": "resumed"},
    )

    class Row:
        data = event.data
        context_id = event.context.id

    entry = described[EVENT_ROOM](Row())
    assert entry["name"] == "Küche"
    assert entry["message"] == "zurück zum Zeitplan"
    assert entry["entity_id"] == "climate.kitchen_heating"
