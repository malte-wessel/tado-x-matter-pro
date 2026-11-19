"""Actions on the room thermostats; area, floor and label targets reach only them."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from homeassistant.components.climate.const import DOMAIN as CLIMATE_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import VolDictType
from homeassistant.util import dt as dt_util
import probatio as vol

from .const import DOMAIN, MAX_TEMPERATURE, MIN_TEMPERATURE

SERVICE_RESUME_SCHEDULE = "resume_schedule"
SERVICE_BOOST = "boost"
SERVICE_SET_OVERRIDE = "set_override"
SERVICE_EXTEND_BLOCK = "extend_block"
PRESETS = ("comfort", "eco")

_TEMPERATURE = vol.All(vol.Coerce(float), vol.Range(min=MIN_TEMPERATURE, max=MAX_TEMPERATURE))
_DURATION = vol.All(cv.positive_time_period, vol.Range(min=timedelta(minutes=1)))

BOOST_SCHEMA: VolDictType = {
    vol.Optional("duration"): _DURATION,
    vol.Optional("temperature"): _TEMPERATURE,
}
# What: a temperature or a preset. Until: a time or a duration; without, the next plan change.
SET_OVERRIDE_SCHEMA: VolDictType = {
    vol.Exclusive("temperature", "what"): _TEMPERATURE,
    vol.Exclusive("preset", "what"): vol.In(PRESETS),
    vol.Exclusive("until", "until"): cv.time,
    vol.Exclusive("duration", "until"): _DURATION,
}
EXTEND_BLOCK_SCHEMA: VolDictType = {vol.Required("until"): cv.time}


def next_local(at: time) -> datetime:
    """Return the next time it is `at` locally, in UTC: today, or tomorrow if that has passed."""
    zone = dt_util.get_default_time_zone()
    now = dt_util.now()
    today = datetime.combine(now.date(), at, tzinfo=zone)
    then = today if today > now else datetime.combine(now.date() + timedelta(days=1), at, zone)
    return dt_util.as_utc(then)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions (once per run, not per entry)."""
    actions: tuple[tuple[str, VolDictType | None, str], ...] = (
        (SERVICE_RESUME_SCHEDULE, None, "async_resume_schedule"),
        (SERVICE_BOOST, BOOST_SCHEMA, "async_boost"),
        (SERVICE_SET_OVERRIDE, SET_OVERRIDE_SCHEMA, "async_set_override"),
        (SERVICE_EXTEND_BLOCK, EXTEND_BLOCK_SCHEMA, "async_extend_block"),
    )
    for name, schema, func in actions:
        service.async_register_platform_entity_service(
            hass, DOMAIN, name, entity_domain=CLIMATE_DOMAIN, schema=schema, func=func
        )
