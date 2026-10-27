"""Tests for the config flow (house), the options flow and the room subentry flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tado_x_matter_pro.const import DOMAIN, SUBENTRY_ROOM, TITLE
from tests.python.conftest import HOUSE_OPTIONS, KITCHEN, FakeTrv

SECTIONS: dict[str, Any] = {"boost": {}, "window_reminder": {}}


async def test_user_flow_creates_the_house_with_defaults(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], SECTIONS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {}
    options = result["options"]
    assert options["frost_temperature"] == 7.0
    assert options["boost"] == {"temperature": 30.0, "duration": {"minutes": 30}}


async def test_only_one_house(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, title=TITLE).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_changes_house_settings(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=HOUSE_OPTIONS)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"frost_temperature": 8.0, **SECTIONS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["frost_temperature"] == 8.0


async def _add_room(hass: HomeAssistant, entry: MockConfigEntry, data: dict[str, Any]) -> Any:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ROOM), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(result["flow_id"], data)


async def test_add_room(
    hass: HomeAssistant,
    setup_house: Callable[..., Awaitable[MockConfigEntry]],
    trvs: dict[str, FakeTrv],
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=HOUSE_OPTIONS)
    entry = await setup_house(entry)
    result = await _add_room(
        hass,
        entry,
        {
            "name": "Kitchen",
            "thermostats": ["climate.kitchen_trv"],
            "schedule": "schedule.ground_floor",
            "window": {"open_delay": {"seconds": 30}},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen"
    await hass.async_block_till_done()
    # the entry reloads with the new room and its thermostat follows the schedule
    room = hass.states.get("climate.kitchen_heating")
    assert room is not None
    assert room.state == "auto"
    trv = hass.states.get("climate.kitchen_trv")
    assert trv is not None
    assert trv.attributes["temperature"] == 21.0


async def test_room_name_defaults_to_the_area_else_the_thermostat(
    hass: HomeAssistant, trvs: dict[str, FakeTrv]
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=HOUSE_OPTIONS)
    entry.add_to_hass(hass)
    in_area = await _add_room(
        hass,
        entry,
        {"thermostats": ["climate.kitchen_trv"], "schedule": "schedule.ground_floor", "window": {}},
    )
    assert in_area["title"] == "Kitchen"
    without_area = await _add_room(
        hass,
        entry,
        {"thermostats": ["climate.bath_trv"], "schedule": "schedule.bathroom", "window": {}},
    )
    assert without_area["title"] == "bath_trv"


async def test_a_thermostat_belongs_to_one_room(
    hass: HomeAssistant, setup_house: Callable[..., Awaitable[MockConfigEntry]]
) -> None:
    entry = await setup_house()
    result = await _add_room(
        hass,
        entry,
        {
            "name": "Other",
            "thermostats": ["climate.kitchen_trv"],
            "schedule": "schedule.ground_floor",
            "window": {},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"thermostats": "thermostat_in_other_room"}


async def test_reconfigure_room(
    hass: HomeAssistant, setup_house: Callable[..., Awaitable[MockConfigEntry]]
) -> None:
    entry = await setup_house()
    subentry_id = next(s.subentry_id for s in entry.subentries.values() if s.title == "Kitchen")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ROOM),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**KITCHEN, "name": "Kitchen", "windows": []}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[subentry_id].data["windows"] == []
    assert hass.states.get("binary_sensor.kitchen_heating_window_open") is None
