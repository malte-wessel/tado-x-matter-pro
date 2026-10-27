"""Constants for Dev House."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "dev_house"
CONF_SPEED: Final = "speed"  # how much faster than real time the rooms warm and cool
CONF_REPORT_DELAY: Final = "report_delay"  # seconds until a written setpoint is reported back
TICK: Final = timedelta(seconds=30)
