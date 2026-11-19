"""Repair issues: bouncing contacts, contacts gone while open, setpoints overwritten in rooms."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.tado_x_matter_pro.const import DOMAIN
from tests.python.conftest import HOUSE_OPTIONS, KITCHEN, FakeTrv, house_entry, set_inputs

type Setup = Callable[..., Awaitable[MockConfigEntry]]
CONTACT = "binary_sensor.kitchen_window"


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_a_bouncing_contact_raises_an_issue_and_changes_nothing(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    entry = await setup_house()
    kitchen = next(s.subentry_id for s in entry.subentries.values() if s.title == "Kitchen")
    writes = len(trvs["climate.kitchen_trv"].writes)
    for _ in range(10):  # a door that does not stay shut
        set_inputs(hass, kitchen_window="on")
        await advance(hass, freezer, 5)
        set_inputs(hass, kitchen_window="off")
        await advance(hass, freezer, 60)
    assert len(trvs["climate.kitchen_trv"].writes) == writes
    chatter = issue(hass, f"chatter_{kitchen}")
    assert chatter is not None
    assert chatter.translation_placeholders == {"room": "Kitchen", "count": "10"}

    await advance(hass, freezer, 3600)  # an hour of calm
    trvs["climate.kitchen_trv"].read(20.4)  # any next decision notices
    await hass.async_block_till_done()
    assert issue(hass, f"chatter_{kitchen}") is None


async def test_a_contact_gone_while_open_raises_an_issue_until_it_reports(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    set_inputs(hass, kitchen_window="on")
    await advance(hass, freezer, 30)
    hass.states.async_set(CONTACT, "unavailable")
    await advance(hass, freezer, 29 * 60)
    assert issue(hass, f"contact_{CONTACT}") is None
    await advance(hass, freezer, 60)
    gone = issue(hass, f"contact_{CONTACT}")
    assert gone is not None
    assert gone.translation_placeholders == {"room": "Kitchen", "contact": CONTACT}

    set_inputs(hass, kitchen_window="off")
    await hass.async_block_till_done()
    assert issue(hass, f"contact_{CONTACT}") is None


async def test_a_contact_gone_while_closed_raises_nothing(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    await setup_house()
    hass.states.async_set(CONTACT, "unavailable")
    await advance(hass, freezer, 31 * 60)
    assert issue(hass, f"contact_{CONTACT}") is None


async def test_changes_in_two_rooms_within_a_minute_look_like_the_tado_app(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    trvs["climate.kitchen_trv"].dial(23.0)
    await advance(hass, freezer, 4)
    assert issue(hass, "tado_overwriting") is None  # one room: a person

    trvs["climate.bath_trv"].dial(22.0)
    await advance(hass, freezer, 4)
    overwriting = issue(hass, "tado_overwriting")
    assert overwriting is not None
    assert overwriting.translation_placeholders == {"rooms": "Bathroom, Kitchen"}
    assert not overwriting.is_persistent


async def test_changes_in_two_rooms_seconds_apart_are_people(
    hass: HomeAssistant,
    setup_house: Setup,
    freezer: FrozenDateTimeFactory,
    trvs: dict[str, FakeTrv],
) -> None:
    await setup_house()
    trvs["climate.kitchen_trv"].dial(23.0)
    await advance(hass, freezer, 4)
    await advance(hass, freezer, 20)  # walking from one dial to the next
    trvs["climate.bath_trv"].dial(22.0)
    await advance(hass, freezer, 4)
    assert issue(hass, "tado_overwriting") is None


async def test_a_rooms_entity_that_is_gone_raises_an_issue_after_the_start(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    entry = house_entry({"Kitchen": {**KITCHEN, "schedule": "schedule.renamed_away"}})
    await setup_house(entry)
    kitchen = next(iter(entry.subentries))
    assert issue(hass, f"missing_{kitchen}") is None  # integrations may still be loading
    await advance(hass, freezer, 5 * 60)
    missing = issue(hass, f"missing_{kitchen}")
    assert missing is not None
    assert missing.translation_placeholders == {
        "room": "Kitchen",
        "entities": "schedule.renamed_away",
    }

    hass.states.async_set("schedule.renamed_away", "on")  # it is back
    await hass.async_block_till_done()
    assert issue(hass, f"missing_{kitchen}") is None


async def test_renaming_a_rooms_thermostat_raises_an_issue(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup_house()
    bathroom = next(s.subentry_id for s in entry.subentries.values() if s.title == "Bathroom")
    await advance(hass, freezer, 5 * 60)
    er.async_get(hass).async_update_entity(
        "climate.bath_tub_trv", new_entity_id="climate.tub_thermostat"
    )
    await hass.async_block_till_done()
    missing = issue(hass, f"missing_{bathroom}")
    assert missing is not None
    assert missing.translation_placeholders == {
        "room": "Bathroom",
        "entities": "climate.bath_tub_trv",
    }


async def test_a_house_entity_that_is_gone_raises_an_issue(
    hass: HomeAssistant, setup_house: Setup, freezer: FrozenDateTimeFactory
) -> None:
    options = {**HOUSE_OPTIONS, "idle_sensors": ["input_boolean.away", "input_boolean.gone"]}
    await setup_house(house_entry(options=options))
    await advance(hass, freezer, 5 * 60)
    missing = issue(hass, "house_inputs_missing")
    assert missing is not None
    assert missing.translation_placeholders == {"entities": "input_boolean.gone"}
    hass.states.async_set("input_boolean.gone", "off")
    await hass.async_block_till_done()
    assert issue(hass, "house_inputs_missing") is None
