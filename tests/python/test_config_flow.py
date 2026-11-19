"""Tests for the config flow (house), the options flow and the room subentry flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tado_x_matter_pro.const import DOMAIN, SUBENTRY_ROOM, TITLE
from tests.python.conftest import HOUSE_OPTIONS, KITCHEN, KITCHEN_DEMAND, FakeTrv, house_entry

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
    assert options["demand_threshold"] == 3.0
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


async def _add_room(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    data: dict[str, Any],
    demand: dict[str, str] | None = None,
) -> Any:
    """Fill in the room, then the demand step (empty unless given)."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ROOM), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    if result["type"] is not FlowResultType.FORM or result["step_id"] != "demand":
        return result
    return await hass.config_entries.subentries.async_configure(result["flow_id"], demand or {})


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
    assert result["step_id"] == "demand"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[subentry_id].data["windows"] == []
    assert hass.states.get("binary_sensor.kitchen_heating_window_open") is None
    assert hass.states.get("sensor.kitchen_heating_back_on") is None


async def test_a_room_takes_a_demand_entity_per_thermostat(
    hass: HomeAssistant, trvs: dict[str, FakeTrv]
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=HOUSE_OPTIONS)
    entry.add_to_hass(hass)
    hass.states.async_set("sensor.bath_demand", "12", {"unit_of_measurement": "%"})
    hass.states.async_set("binary_sensor.tub_pipe_hot", "off")
    result = await _add_room(
        hass,
        entry,
        {
            "name": "Bathroom",
            "thermostats": ["climate.bath_trv", "climate.bath_tub_trv"],
            "schedule": "schedule.bathroom",
            "window": {},
        },
        {"thermostat_1": "sensor.bath_demand", "thermostat_2": "binary_sensor.tub_pipe_hot"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["demand"] == {
        "climate.bath_trv": "sensor.bath_demand",
        "climate.bath_tub_trv": "binary_sensor.tub_pipe_hot",
    }


async def test_a_demand_sensor_must_report_a_number(
    hass: HomeAssistant, trvs: dict[str, FakeTrv]
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, options=HOUSE_OPTIONS)
    entry.add_to_hass(hass)
    hass.states.async_set("sensor.kitchen_mood", "cosy")
    result = await _add_room(
        hass,
        entry,
        {"thermostats": ["climate.kitchen_trv"], "schedule": "schedule.ground_floor", "window": {}},
        {"thermostat_1": "sensor.kitchen_mood"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "demand"
    assert result["errors"] == {"thermostat_1": "demand_not_numeric"}


async def test_reconfigure_keeps_and_removes_demand_entities(
    hass: HomeAssistant, setup_house: Callable[..., Awaitable[MockConfigEntry]]
) -> None:
    hass.states.async_set("sensor.kitchen_demand", "0", {"unit_of_measurement": "%"})
    entry = await setup_house(house_entry({"Kitchen": {**KITCHEN, "demand": KITCHEN_DEMAND}}))
    subentry_id = next(iter(entry.subentries))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ROOM),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**KITCHEN, "name": "Kitchen"}
    )
    assert result["step_id"] == "demand"
    assert result["data_schema"] is not None
    schema = result["data_schema"].schema
    key = next(k for k in schema if k == "thermostat_1")
    assert key.description == {"suggested_value": "sensor.kitchen_demand"}
    # labelled with the thermostat's name, its entity id below
    assert result["description_placeholders"] == {
        "thermostat_1": "kitchen_trv",
        "thermostat_1_entity": "climate.kitchen_trv",
    }

    assert hass.states.get("sensor.kitchen_heating_kitchen_trv_heating") is not None

    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[subentry_id].data["demand"] == {}
    # without a demand entity the thermostat's status sensor goes, also from the registry
    assert hass.states.get("sensor.kitchen_heating_kitchen_trv_heating") is None
    assert er.async_get(hass).async_get("sensor.kitchen_heating_kitchen_trv_heating") is None


async def test_a_room_thermostat_of_the_integration_is_no_rooms_thermostat(
    hass: HomeAssistant, setup_house: Callable[..., Awaitable[MockConfigEntry]]
) -> None:
    entry = await setup_house()
    with pytest.raises(InvalidData):  # the picker does not offer it, and refuses it if sent
        await _add_room(
            hass,
            entry,
            {
                "thermostats": ["climate.kitchen_heating"],
                "schedule": "schedule.bathroom",
                "window": {},
            },
        )


async def test_only_below_needs_an_outdoor_sensor(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"boost": {}, "window_reminder": {"only_below": 12}}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "only_below_needs_outdoor_sensor"}


async def test_the_notify_list_leaves_out_send_message(hass: HomeAssistant) -> None:
    for name in ("send_message", "mobile_app_phone"):
        hass.services.async_register("notify", name, lambda _call: None)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["data_schema"] is not None
    reminder = result["data_schema"].schema["window_reminder"].schema.schema
    notify = next(v for k, v in reminder.items() if k == "notify")
    assert notify.config["options"] == ["notify.mobile_app_phone"]
