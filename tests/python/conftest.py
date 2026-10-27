"""Shared pytest fixtures: fake Tado X-like thermostats and a configured house."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigSubentryData
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.tado_x_matter_pro.const import DOMAIN, SUBENTRY_ROOM, TITLE

TRVS = ("climate.kitchen_trv", "climate.bath_trv", "climate.bath_tub_trv")


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ for every test."""


class FakeTrv(ClimateEntity):
    """A thermostat as HA's Matter integration shows a Tado X: off/heat, no action.

    A write reports the mode and the setpoint separately, like Matter; `writes` records the
    calls; `dial` changes it the way the device itself would, without a Home Assistant context.
    """

    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5
    _attr_max_temp = 30
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, entity_id: str) -> None:
        """Start in heat at 18 °C; its device also carries a precise temperature sensor."""
        self.entity_id = entity_id
        self._attr_unique_id = entity_id
        self._attr_name = entity_id.split(".")[1]
        self._attr_device_info = DeviceInfo(
            identifiers={("fake_trv", entity_id)}, name=self._attr_name
        )
        self.sensor = FakeTemperature(entity_id, self._attr_device_info)
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_target_temperature = 18.0
        self._attr_current_temperature = 20.0
        self.writes: list[tuple[str, float | None]] = []

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Mode first, then the setpoint (two reports)."""
        mode = kwargs.get(ATTR_HVAC_MODE)
        temperature = kwargs.get(ATTR_TEMPERATURE)
        self.writes.append((str(mode or self._attr_hvac_mode), temperature))
        if mode is not None and mode != self._attr_hvac_mode:
            self._attr_hvac_mode = HVACMode(mode)
            self.async_write_ha_state()
        if temperature is not None:
            self._attr_target_temperature = float(temperature)
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Switch off or on."""
        self.writes.append((str(hvac_mode), None))
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    def read(self, temperature: float) -> None:
        """A new reading: the precise sensor (0.01 °C) and the climate's own (0.1 °C)."""
        self.sensor.set(temperature)
        self._attr_current_temperature = round(temperature, 1)
        self.async_write_ha_state()

    def dial(self, temperature: float | None = None, hvac_mode: str | None = None) -> None:
        """Change it at the device: no Home Assistant context."""
        if hvac_mode is not None:
            self._attr_hvac_mode = HVACMode(hvac_mode)
        if temperature is not None:
            self._attr_target_temperature = temperature
        self.async_set_context(Context())
        self.async_write_ha_state()


class FakeTemperature(SensorEntity):
    """The thermostat's own temperature sensor; every `set` writes (unchanged = a report)."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, thermostat: str, device: DeviceInfo) -> None:
        """Belong to the thermostat's device."""
        self.entity_id = f"sensor.{thermostat.split('.')[1]}_temperature"
        self._attr_unique_id = self.entity_id
        self._attr_device_info = device
        self._attr_native_value = 20.0

    def set(self, value: float) -> None:
        """A new reading."""
        self._attr_native_value = round(value, 2)
        self.async_write_ha_state()


class FakeTrvFlow(ConfigFlow):
    """The fake integration's (unused) config flow; config entries need a handler."""

    VERSION = 1


@pytest.fixture
async def trvs(hass: HomeAssistant) -> AsyncIterator[dict[str, FakeTrv]]:
    """Three fake thermostats in a fake integration."""
    entities = {entity_id: FakeTrv(entity_id) for entity_id in TRVS}

    async def setup_climate(
        _hass: HomeAssistant, _entry: ConfigEntry, add: AddConfigEntryEntitiesCallback
    ) -> None:
        add(list(entities.values()))

    async def setup_sensor(
        _hass: HomeAssistant, _entry: ConfigEntry, add: AddConfigEntryEntitiesCallback
    ) -> None:
        add([trv.sensor for trv in entities.values()])

    async def setup_entry(_hass: HomeAssistant, entry: ConfigEntry) -> bool:
        await hass.config_entries.async_forward_entry_setups(entry, ["climate", "sensor"])
        return True

    mock_integration(hass, MockModule("fake_trv", async_setup_entry=setup_entry))
    mock_platform(hass, "fake_trv.climate", MockPlatform(async_setup_entry=setup_climate))
    mock_platform(hass, "fake_trv.sensor", MockPlatform(async_setup_entry=setup_sensor))
    mock_platform(hass, "fake_trv.config_flow")
    assert await async_setup_component(hass, "climate", {})
    with mock_config_flow("fake_trv", FakeTrvFlow):
        entry = MockConfigEntry(domain="fake_trv")
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        # The kitchen thermostat sits in an area, the bathroom ones don't.
        kitchen = ar.async_get(hass).async_create("Kitchen")
        device_id = er.async_get(hass).async_get("climate.kitchen_trv").device_id  # type: ignore[union-attr]
        dr.async_get(hass).async_update_device(device_id, area_id=kitchen.id)  # type: ignore[arg-type]
        yield entities


KITCHEN: dict[str, Any] = {
    "thermostats": ["climate.kitchen_trv"],
    "schedule": "schedule.ground_floor",
    "windows": ["binary_sensor.kitchen_window"],
    "window": {"open_delay": {"seconds": 30}, "close_delay": {"minutes": 5}, "remind_after": 30},
}
BATHROOM: dict[str, Any] = {
    "thermostats": ["climate.bath_trv", "climate.bath_tub_trv"],
    "schedule": "schedule.bathroom",
    "windows": [],
    "window": {"open_delay": {"seconds": 30}, "close_delay": {"minutes": 5}, "remind_after": 0},
}
HOUSE_OPTIONS: dict[str, Any] = {
    "idle_sensors": ["input_boolean.away"],
    "frost_temperature": 7.0,
    "boost": {"temperature": 30.0, "duration": {"minutes": 30}},
    "window_reminder": {"notify": []},
}


def house_entry(rooms: dict[str, dict[str, Any]] | None = None) -> MockConfigEntry:
    """The heating entry with the given rooms (title → subentry data)."""
    rooms = {"Kitchen": KITCHEN, "Bathroom": BATHROOM} if rooms is None else rooms
    return MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        options=HOUSE_OPTIONS,
        subentries_data=[
            ConfigSubentryData(data=data, subentry_type=SUBENTRY_ROOM, title=title, unique_id=None)
            for title, data in rooms.items()
        ],
    )


def set_inputs(hass: HomeAssistant, **states: str) -> None:
    """Set schedules ('on'/'off'), windows and the away switch by object id."""
    domains = {
        "ground_floor": "schedule",
        "bathroom": "schedule",
        "kitchen_window": "binary_sensor",
        "away": "input_boolean",
    }
    for object_id, value in states.items():
        hass.states.async_set(f"{domains[object_id]}.{object_id}", value)


@pytest.fixture
def setup_house(
    hass: HomeAssistant, trvs: dict[str, FakeTrv]
) -> Callable[..., Awaitable[MockConfigEntry]]:
    """Set up the heating with inputs in a known state; returns the entry."""

    async def _setup(entry: MockConfigEntry | None = None) -> MockConfigEntry:
        set_inputs(hass, ground_floor="on", bathroom="off", kitchen_window="off", away="off")
        entry = entry or house_entry()
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup
