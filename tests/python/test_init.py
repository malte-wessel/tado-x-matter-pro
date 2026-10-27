"""Tests for setup, unload and entry migration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tado_x_matter_pro.const import DOMAIN, TITLE


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    """The entry loads, reloads and unloads cleanly."""
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    unloaded = hass.config_entries.async_get_entry(entry.entry_id)
    assert unloaded is not None
    assert unloaded.state is ConfigEntryState.NOT_LOADED


async def test_newer_entry_version_is_refused(hass: HomeAssistant) -> None:
    """An entry written by a newer version is not touched."""
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, version=2)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    assert entry.version == 2


async def test_older_minor_version_is_migrated(hass: HomeAssistant) -> None:
    """An entry from an older minor version is brought up to date."""
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE, version=1, minor_version=0)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (entry.version, entry.minor_version) == (1, 1)
