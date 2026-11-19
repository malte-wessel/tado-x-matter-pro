"""Stored rooms survive upgrades: older store versions load into the current shape."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.tado_x_matter_pro.const import DOMAIN
from custom_components.tado_x_matter_pro.store import HeatingStore, state_from_dict

FIXTURES = Path(__file__).parent.parent / "fixtures" / "storage"


async def test_a_1_2_store_drops_the_inferred_statuses(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage[DOMAIN] = json.loads((FIXTURES / "v1_2.json").read_text())
    store = HeatingStore(hass)
    await store.async_load({"room_a"})
    room = store.room("room_a")
    assert "status" not in room
    assert room["heating_temperature"] == 21.5
    assert room["idle_temperature"] == 17.0
    assert room["last_known"] == {"climate.room_a_trv": ["heat", 21.5]}


async def test_a_1_3_store_gets_no_boost_and_no_preset(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage[DOMAIN] = json.loads((FIXTURES / "v1_3.json").read_text())
    store = HeatingStore(hass)
    await store.async_load({"room_a"})
    state = store.room("room_a")["state"]
    assert state["boost"] is None
    assert state["override"] == {
        "temperature": 23.0,
        "expires": "next_change",
        "window_ack": False,
        "preset": None,
    }
    restored = state_from_dict(state)
    assert restored.boost is None
    assert restored.override is not None
    assert restored.override.temperature == 23.0


async def test_a_1_4_store_gets_no_reminder_state(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage[DOMAIN] = json.loads((FIXTURES / "v1_4.json").read_text())
    store = HeatingStore(hass)
    await store.async_load({"room_a"})
    state = store.room("room_a")["state"]
    assert state["window_open_since"] is None
    assert state["reminded"] is False
    assert state_from_dict(state).window.value == "open"


async def test_a_1_5_store_gets_an_empty_last_command(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage[DOMAIN] = json.loads((FIXTURES / "v1_5.json").read_text())
    store = HeatingStore(hass)
    await store.async_load({"room_a"})
    room = store.room("room_a")
    assert room.get("last_commanded") == {}
    assert room["last_known"] == {"climate.room_a_trv": ["heat", 21.5]}
