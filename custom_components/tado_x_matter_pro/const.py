"""Constants for Tado X Matter Pro."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tado_x_matter_pro"
TITLE: Final = "Heating"

STORAGE_KEY: Final = DOMAIN
# Major: breaking shape changes; minor: additive ones. Both migrate in store.py.
STORAGE_VERSION: Final = 1
STORAGE_MINOR_VERSION: Final = 1
