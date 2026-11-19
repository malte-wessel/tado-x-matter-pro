"""What the recorder keeps of the integration's entities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import history
from homeassistant.components.recorder.core import Recorder
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from tests.python.conftest import KITCHEN, KITCHEN_DEMAND, FakeTrv, house_entry

type Setup = Callable[..., Awaitable[MockConfigEntry]]
STATUS = "sensor.kitchen_heating_kitchen_trv_heating"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(
    recorder_mock: Recorder,  # the recorder must start before hass
    enable_custom_integrations: None,
) -> None:
    """Load custom_components/ with a recorder running."""


async def test_the_demand_is_not_recorded_twice(
    hass: HomeAssistant,
    recorder_mock: Recorder,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    start = dt_util.utcnow() - timedelta(seconds=1)
    hass.states.async_set("sensor.kitchen_demand", "40", {"unit_of_measurement": "%"})
    await setup_house(house_entry({"Kitchen": {**KITCHEN, "demand": KITCHEN_DEMAND}}))
    hass.states.async_set("sensor.kitchen_demand", "0", {"unit_of_measurement": "%"})
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    state = hass.states.get(STATUS)
    assert state is not None
    assert state.attributes["demand"] == 0.0  # on the live state, for cards

    await async_wait_recording_done(hass)
    recorded = await recorder_mock.async_add_executor_job(
        history.state_changes_during_period, hass, start, dt_util.utcnow(), STATUS
    )
    states = [row.state for row in recorded[STATUS] if row.state != "unavailable"]  # before start
    assert states == ["heating", "reached"]
    for row in recorded[STATUS]:
        assert "demand" not in row.attributes
