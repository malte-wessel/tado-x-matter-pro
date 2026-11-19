"""The Mode sensor's next change, from a real schedule helper's blocks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tado_x_matter_pro.controller import expand_week
from custom_components.tado_x_matter_pro.engine.forecast import Block
from tests.python.conftest import KITCHEN, house_entry

type Setup = Callable[..., Awaitable[MockConfigEntry]]
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Every evening 20:00–24:00 at 22 °C, continuing until 01:00 at 22 °C; mornings 06:00–08:00.
EVENINGS = {
    day: [
        {"from": "00:00:00", "to": "01:00:00", "data": {"temperature": 22}},
        {"from": "06:00:00", "to": "08:00:00"},
        {"from": "20:00:00", "to": "24:00:00", "data": {"temperature": 22}},
    ]
    for day in DAYS
}


def local(hour: int, minute: int = 0, days: int = 0) -> datetime:
    today = dt_util.now().date() + timedelta(days=days)
    return datetime.combine(today, time(hour, minute), dt_util.get_default_time_zone())


def attributes(hass: HomeAssistant) -> dict[str, Any]:
    state = hass.states.get("sensor.kitchen_heating_mode")
    assert state is not None
    return dict(state.attributes)


# The schedule helper keeps its own timer to its next block edge.
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_the_next_change_skips_midnight_and_knows_block_temperatures(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(dt_util.as_utc(local(21)))
    assert await async_setup_component(
        hass, "schedule", {"schedule": {"evenings": {"name": "Evenings", **EVENINGS}}}
    )
    entry = house_entry({"Kitchen": {**KITCHEN, "schedule": "schedule.evenings"}})
    entry.add_to_hass(hass)
    hass.states.async_set("binary_sensor.kitchen_window", "off")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    shown = attributes(hass)
    assert shown["target"] == 22.0
    # 24:00 continues at 22 °C until 01:00: the next change is then, to eco
    assert dt_util.parse_datetime(shown["next_change"]) == local(1, days=1)
    assert shown["next_target"] == 18.0
    sensor = hass.states.get("sensor.kitchen_heating_next_change")
    assert sensor is not None
    assert dt_util.parse_datetime(sensor.state) == local(1, days=1)
    assert sensor.attributes["target"] == 18.0


def test_expanding_a_week_into_dated_blocks() -> None:
    now = dt_util.as_utc(local(12))
    week = {
        DAYS[dt_util.now().weekday()]: [
            {"from": time(20), "to": time.max, "data": {"temperature": "22.5"}},  # 24:00
            {"from": "06:00:00", "to": "07:00:00"},
        ]
    }
    blocks = [b for b in expand_week(week, now) if b.start.date() == now.date() or b.end > now]
    evening = Block(dt_util.as_utc(local(20)), dt_util.as_utc(local(0, days=1)), 22.5)
    assert evening in blocks
    assert Block(dt_util.as_utc(local(6)), dt_util.as_utc(local(7))) in blocks
