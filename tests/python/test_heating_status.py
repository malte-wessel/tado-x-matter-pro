"""The inferred heating status per thermostat and as the room thermostat's action."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
import random

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from tests.python.conftest import FakeTrv, set_inputs

type Setup = Callable[..., Awaitable[MockConfigEntry]]
STATUS = "sensor.kitchen_heating_kitchen_trv_heating"


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def status(hass: HomeAssistant) -> tuple[str, float | None]:
    state = hass.states.get(STATUS)
    assert state is not None
    return state.state, state.attributes.get("trend")


def action(hass: HomeAssistant) -> str | None:
    state = hass.states.get("climate.kitchen_heating")
    assert state is not None
    return state.attributes.get("hvac_action")


async def test_heating_then_reached_then_off(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    trv = trvs["climate.kitchen_trv"]
    trv.read(19.0)
    await setup_house()  # the kitchen block is on: setpoint 21
    assert status(hass)[0] == "heating"  # below the setpoint and not cooling
    assert action(hass) == "heating"

    reading = 19.0
    for _ in range(10):  # the radiator warms: +0.3 °C per minute
        reading += 0.3
        trv.read(reading)
        await advance(hass, freezer, 60)
    state, trend = status(hass)
    assert state == "heating"
    assert trend is not None
    assert trend > 5

    for _ in range(20):  # setpoint reached, the valve closed: the reading eases off above it
        reading -= 0.02
        trv.read(reading)
        await advance(hass, freezer, 60)
    assert status(hass)[0] == "reached"
    assert action(hass) == "idle"

    set_inputs(hass, kitchen_window="on")
    await hass.async_block_till_done()
    await advance(hass, freezer, 30)
    assert status(hass)[0] == "off"
    assert action(hass) == "off"


async def test_trend_matches_home_assistants_derivative_sensor(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    # HA's own derivative helper on the same sensor, configured like the old trend helpers
    reference_entry = MockConfigEntry(
        domain="derivative",
        title="reference",
        options={
            "name": "reference",
            "source": "sensor.kitchen_trv_temperature",
            "round": 2.0,
            "unit_time": "h",
            "time_window": {"minutes": 20},
            "max_sub_interval": {"minutes": 5},
        },
    )
    reference_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(reference_entry.entry_id)
    await hass.async_block_till_done()
    reference_id = er.async_get(hass).async_get_entity_id(
        "sensor", "derivative", reference_entry.entry_id
    )
    assert reference_id is not None
    rng = random.Random(42)
    trv = trvs["climate.kitchen_trv"]
    reading = 20.0
    compared = 0
    for step in range(300):
        if rng.random() < 0.7:
            reading += rng.choice([-0.03, -0.01, 0.01, 0.02, 0.05])
        trv.sensor.set(reading)  # unchanged values are reports, as on the real device
        await hass.async_block_till_done()
        # mostly 1–3 min apart like a Tado X, sometimes a quiet stretch past the sub-interval
        await advance(hass, freezer, rng.choice([60, 90, 120, 180]) if step % 25 else 900)
        reference = hass.states.get(reference_id)
        assert reference is not None
        ours = status(hass)[1]
        if reference.state not in ("unknown", "unavailable") and ours is not None:
            # one unit in the last digit: HA rounds Decimals, we round floats
            assert abs(float(reference.state) - ours) <= 0.01 + 1e-9, step
            compared += 1
    assert compared > 250
