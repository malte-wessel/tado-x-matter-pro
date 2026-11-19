"""Removing rooms and the integration leaves nothing behind; updates keep or refuse stored data."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.tado_x_matter_pro.const import DOMAIN
from tests.python.conftest import FakeTrv, house_entry

type Setup = Callable[..., Awaitable[MockConfigEntry]]


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def ours(hass: HomeAssistant, entry: MockConfigEntry) -> tuple[list[Any], list[Any], list[Any]]:
    """The entry's entities, devices and the integration's repair issues."""
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    issues = [i for (domain, _), i in ir.async_get(hass).issues.items() if domain == DOMAIN]
    return entities, devices, issues


async def test_removing_the_integration_removes_everything(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
    hass_storage: dict[str, Any],
) -> None:
    entry = await setup_house()
    trvs["climate.kitchen_trv"].dial(23.0)  # two rooms at once: an issue
    trvs["climate.bath_trv"].dial(22.0)
    await advance(hass, freezer, 5)
    entities, devices, issues = ours(hass, entry)
    assert entities
    assert devices
    assert issues
    assert DOMAIN in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ours(hass, entry) == ([], [], [])
    assert DOMAIN not in hass_storage
    # the thermostats keep what they had, nothing is written on the way out
    assert trvs["climate.kitchen_trv"].hvac_mode == "heat"


async def test_removing_a_room_removes_its_device_entities_and_stored_state(
    hass: HomeAssistant, setup_house: Setup, hass_storage: dict[str, Any]
) -> None:
    entry = await setup_house()
    kitchen = next(s.subentry_id for s in entry.subentries.values() if s.title == "Kitchen")
    bathroom = next(s.subentry_id for s in entry.subentries.values() if s.title == "Bathroom")

    assert hass.config_entries.async_remove_subentry(entry, kitchen)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    remaining = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert all(e.config_subentry_id != kitchen for e in remaining)
    assert any(e.config_subentry_id == bathroom for e in remaining)
    assert (
        dr.async_get(hass).async_get_device_by_identifier((DOMAIN, kitchen), entry.entry_id) is None
    )
    assert hass.states.get("climate.kitchen_heating") is None
    assert set(hass_storage[DOMAIN]["data"]["rooms"]) == {bathroom}


async def test_a_boost_and_a_hold_survive_a_restart(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup_house()
    await hass.services.async_call(
        DOMAIN, "boost", {"entity_id": "climate.kitchen_heating"}, blocking=True
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.kitchen_heating_mode")
    assert state is not None
    assert state.state == "boost"
    await advance(hass, freezer, 30 * 60)
    assert hass.states.get("sensor.kitchen_heating_mode").state == "schedule"  # type: ignore[union-attr]


async def test_a_store_from_a_newer_version_is_refused_untouched(
    hass: HomeAssistant, setup_house: Setup, trvs: dict[str, FakeTrv], hass_storage: dict[str, Any]
) -> None:
    newer = {"version": 2, "minor_version": 1, "key": DOMAIN, "data": {"whatever": True}}
    hass_storage[DOMAIN] = newer
    entry = house_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert hass_storage[DOMAIN] == newer
    assert trvs["climate.kitchen_trv"].writes == []


async def test_a_store_from_a_newer_minor_version_still_loads(
    hass: HomeAssistant, setup_house: Setup, hass_storage: dict[str, Any]
) -> None:
    # A downgrade from a newer beta: unknown keys are kept, known ones are used.
    entry = house_entry()
    room = {
        "heating_temperature": 22.5,
        "idle_temperature": 17.0,
        "last_known": {},
        "something_new": [1, 2],
    }
    hass_storage[DOMAIN] = {"version": 1, "minor_version": 99, "key": DOMAIN, "data": {"rooms": {}}}
    entry.add_to_hass(hass)
    kitchen = next(s.subentry_id for s in entry.subentries.values() if s.title == "Kitchen")
    hass_storage[DOMAIN]["data"]["rooms"][kitchen] = room
    await setup_house(entry)
    assert entry.state is ConfigEntryState.LOADED
    number = hass.states.get("number.kitchen_heating_comfort_temperature")
    assert number is not None
    assert number.state == "22.5"
