"""The window reminder: a notification once a window has been open too long, if it is cold."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from tests.python.conftest import HOUSE_OPTIONS, house_entry, set_inputs

type Setup = Callable[..., Awaitable[MockConfigEntry]]
OVERDUE = "binary_sensor.kitchen_heating_window_open_too_long"
REMINDER = {
    "outdoor_sensor": "sensor.outdoor",
    "only_below": 12.0,
    "notify": ["notify.phone"],
}


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def setup(hass: HomeAssistant, setup_house: Setup, outdoor: float) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def phone(call: ServiceCall) -> None:
        sent.append(dict(call.data))

    hass.services.async_register("notify", "phone", phone)
    hass.states.async_set("sensor.outdoor", str(outdoor))
    await setup_house(house_entry(options={**HOUSE_OPTIONS, "window_reminder": REMINDER}))
    return sent


async def test_a_window_open_for_30_minutes_in_the_cold_is_reminded_once(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    sent = await setup(hass, setup_house, outdoor=4.0)
    set_inputs(hass, kitchen_window="on")
    await advance(hass, freezer, 30)  # open: the room is off
    await advance(hass, freezer, 29 * 60)
    assert sent == []
    assert hass.states.get(OVERDUE).state == "off"  # type: ignore[union-attr]

    await advance(hass, freezer, 60)
    assert sent == [
        {"title": "Window open", "message": "Kitchen: a window has been open for 30 minutes."}
    ]
    assert hass.states.get(OVERDUE).state == "on"  # type: ignore[union-attr]
    await advance(hass, freezer, 30 * 60)
    assert len(sent) == 1  # once per opening

    set_inputs(hass, kitchen_window="off")
    await hass.async_block_till_done()
    assert hass.states.get(OVERDUE).state == "off"  # type: ignore[union-attr]


async def test_no_reminder_while_it_is_warm_outside(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    sent = await setup(hass, setup_house, outdoor=16.0)
    set_inputs(hass, kitchen_window="on")
    await advance(hass, freezer, 30)
    await advance(hass, freezer, 31 * 60)
    assert sent == []
    assert hass.states.get(OVERDUE).state == "on"  # type: ignore[union-attr]

    hass.states.async_set("sensor.outdoor", "9.5")  # it got cold: remind now
    await hass.async_block_till_done()
    assert len(sent) == 1
