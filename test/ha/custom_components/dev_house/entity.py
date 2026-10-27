"""Base entity: belongs to a simulated device, rewrites its state after every simulation step."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .sim import Simulation


class DevHouseEntity(Entity):
    """An entity of the simulated house with a fixed entity id."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, sim: Simulation, entity_id: str, device: DeviceInfo, name: str | None
    ) -> None:
        """Pin the entity id, so it is the same in every fresh dev instance."""
        self.sim = sim
        self.entity_id = entity_id
        self._attr_unique_id = entity_id
        self._attr_device_info = device
        self._attr_name = name

    async def async_added_to_hass(self) -> None:
        """Follow the simulation."""
        self.async_on_remove(self.sim.subscribe(self.async_write_ha_state))


def device(identifier: str, name: str, model: str, manufacturer: str, area: str) -> DeviceInfo:
    """Device info for a simulated device in an area."""
    return DeviceInfo(
        identifiers={(DOMAIN, identifier)},
        name=name,
        model=model,
        manufacturer=manufacturer,
        suggested_area=area,
    )


def trv_device(object_id: str, name: str, area: str) -> DeviceInfo:
    """The device of a simulated Tado X thermostat (climate + temperature + humidity)."""
    return device(object_id, name, "Smart Radiator Thermostat X", "Dev House (Tado X-like)", area)
