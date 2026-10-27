"""Dev House is configured in YAML; the flow only imports it."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class DevHouseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Import `dev_house:` from configuration.yaml."""

    VERSION = 1

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Create the single entry, or update its options from YAML."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured(updates=import_data)
        return self.async_create_entry(title="Dev House", data=import_data)
