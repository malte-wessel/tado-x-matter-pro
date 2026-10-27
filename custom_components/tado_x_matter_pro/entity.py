"""Base entity: one device per room, updated after every decision of its controller."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .controller import RoomController


class RoomEntity(Entity):
    """An entity of a room."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, room: RoomController, key: str) -> None:
        """Attach the entity to the room's device."""
        self.room = room
        self._attr_unique_id = f"{room.room_id}_{key}"
        area = room.area_name
        # In an area the device is just "Heating": HA puts the area in front of entity ids
        # (kitchen_heating_mode). Without an area it carries the room's name instead.
        device = DeviceInfo(
            identifiers={(DOMAIN, room.room_id)},
            manufacturer="Tado X Matter Pro",
            model="Room",
            entry_type=DeviceEntryType.SERVICE,
        )
        if area:
            device["suggested_area"] = area
            device["translation_key"] = "room"
        else:
            device["name"] = room.name
        self._attr_device_info = device

    @property
    def available(self) -> bool:
        """Available once the room has decided (after Home Assistant started)."""
        return self.room.desired is not None

    async def async_added_to_hass(self) -> None:
        """Follow the room's decisions."""
        self.async_on_remove(self.room.add_listener(self.async_write_ha_state))
