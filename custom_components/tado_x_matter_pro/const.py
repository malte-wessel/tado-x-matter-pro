"""Constants for Tado X Matter Pro."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tado_x_matter_pro"
TITLE: Final = "Heating"
SUBENTRY_ROOM: Final = "room"

STORAGE_KEY: Final = DOMAIN
# Major: breaking shape changes; minor: additive ones. Both migrate in store.py.
STORAGE_VERSION: Final = 1
STORAGE_MINOR_VERSION: Final = 2

# House options (config entry options)
CONF_IDLE_SENSORS: Final = "idle_sensors"
CONF_FROST_TEMPERATURE: Final = "frost_temperature"
SECTION_BOOST: Final = "boost"
CONF_BOOST_TEMPERATURE: Final = "temperature"
CONF_BOOST_DURATION: Final = "duration"
SECTION_REMINDER: Final = "window_reminder"
CONF_OUTDOOR_SENSOR: Final = "outdoor_sensor"
CONF_ONLY_BELOW: Final = "only_below"
CONF_NOTIFY: Final = "notify"

DEFAULT_FROST_TEMPERATURE: Final = 7.0
DEFAULT_BOOST_TEMPERATURE: Final = 30.0
DEFAULT_BOOST_MINUTES: Final = 30

# Room options (subentry data)
CONF_THERMOSTATS: Final = "thermostats"
CONF_SCHEDULE: Final = "schedule"
CONF_WINDOWS: Final = "windows"
CONF_ROOM_SENSOR: Final = "room_sensor"
SECTION_WINDOW: Final = "window"
CONF_OPEN_DELAY: Final = "open_delay"
CONF_CLOSE_DELAY: Final = "close_delay"
CONF_REMIND_AFTER: Final = "remind_after"

DEFAULT_OPEN_DELAY_SECONDS: Final = 30
DEFAULT_CLOSE_DELAY_MINUTES: Final = 5
DEFAULT_REMIND_AFTER_MINUTES: Final = 30

DEFAULT_HEATING_TEMPERATURE: Final = 21.0
DEFAULT_IDLE_TEMPERATURE: Final = 18.0
MIN_TEMPERATURE: Final = 5.0
MAX_TEMPERATURE: Final = 30.0
