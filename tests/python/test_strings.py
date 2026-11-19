"""Strings and icons agree with each other and with what the entities use."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).parent.parent.parent / "custom_components" / "tado_x_matter_pro"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((PACKAGE / name).read_text())
    return data


def keys(tree: dict[str, Any], prefix: str = "") -> set[str]:
    found: set[str] = set()
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        found |= keys(value, path) if isinstance(value, dict) else {path}
    return found


def test_the_translations_have_the_same_keys_as_the_strings() -> None:
    strings = keys(load("strings.json"))
    for language in ("en", "de"):
        assert keys(load(f"translations/{language}.json")) == strings, language


def test_every_icon_belongs_to_an_entity_or_action_with_strings() -> None:
    strings = load("strings.json")
    icons = load("icons.json")
    for platform, entities in icons["entity"].items():
        for key, icon in entities.items():
            entity = strings["entity"][platform][key]  # KeyError: an icon for nothing
            for state in icon.get("state", {}):
                assert state in entity["state"], f"{platform}.{key}: {state}"
    assert set(icons["services"]) <= set(strings["services"])
