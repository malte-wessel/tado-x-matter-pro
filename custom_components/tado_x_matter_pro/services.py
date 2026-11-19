"""Actions on the room thermostats; area, floor and label targets reach only them."""

from __future__ import annotations

from homeassistant.components.climate.const import DOMAIN as CLIMATE_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import service

from .const import DOMAIN

SERVICE_RESUME_SCHEDULE = "resume_schedule"


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions (once per run, not per entry)."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_RESUME_SCHEDULE,
        entity_domain=CLIMATE_DOMAIN,
        schema=None,
        func="async_resume_schedule",
    )
