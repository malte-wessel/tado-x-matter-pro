"""Diagnostics explain what a room decided and why, without notify targets."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
    get_diagnostics_for_device,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from tests.python.conftest import HOUSE_OPTIONS, FakeTrv, house_entry

type Setup = Callable[..., Awaitable[MockConfigEntry]]


async def test_a_dial_turn_shows_up_in_the_trace(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    entry = house_entry(
        options={**HOUSE_OPTIONS, "window_reminder": {"notify": ["notify.mobile_app_phone"]}}
    )
    await setup_house(entry)
    trvs["climate.kitchen_trv"].dial(23.0)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=4))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert data["house"]["window_reminder"] == {"notify": "**REDACTED**"}
    rooms: dict[str, Any] = data["rooms"]
    kitchen = next(room for room in rooms.values() if room["name"] == "Kitchen")
    assert kitchen["desired"]["mode"] == "manual"
    assert kitchen["counters"]["report_external"] == 1
    trace = [(e["what"], e.get("report"), e.get("event")) for e in kitchen["trace"]]
    assert ("report", "external", None) in trace
    assert (
        "decision",
        None,
        "ExternalChange(hvac_mode='heat', temperature=23.0)",
    ) in trace
    assert kitchen["heating"]["climate.kitchen_trv"]["sensor"] == "sensor.kitchen_trv_temperature"

    climate = er.async_get(hass).async_get("climate.kitchen_heating")
    assert climate is not None
    device = dr.async_get(hass).async_get(climate.device_id)  # type: ignore[arg-type]
    assert device is not None
    room = await get_diagnostics_for_device(hass, hass_client, entry, device)
    assert room["name"] == "Kitchen"
