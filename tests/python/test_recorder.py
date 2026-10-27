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

from tests.python.conftest import FakeTrv

type Setup = Callable[..., Awaitable[MockConfigEntry]]
STATUS = "sensor.kitchen_heating_kitchen_trv_heating"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(
    recorder_mock: Recorder,  # the recorder must start before hass
    enable_custom_integrations: None,
) -> None:
    """Load custom_components/ with a recorder running."""


async def test_reading_and_trend_are_not_recorded(
    hass: HomeAssistant,
    recorder_mock: Recorder,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    start = dt_util.utcnow() - timedelta(seconds=1)
    await setup_house()
    trvs["climate.kitchen_trv"].read(19.5)
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    state = hass.states.get(STATUS)
    assert state is not None
    assert "trend" in state.attributes  # still on the live state, for cards

    await async_wait_recording_done(hass)
    recorded = await recorder_mock.async_add_executor_job(
        history.state_changes_during_period, hass, start, dt_util.utcnow(), STATUS
    )
    assert recorded[STATUS]
    for row in recorded[STATUS]:
        assert "trend" not in row.attributes
        assert "temperature" not in row.attributes
