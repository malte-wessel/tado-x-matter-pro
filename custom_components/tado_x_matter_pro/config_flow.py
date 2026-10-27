"""Config flow (the house), options flow and the room subentry flow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.selector import (
    DurationSelector,
    DurationSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
import probatio as vol

from .const import (
    CONF_BOOST_DURATION,
    CONF_BOOST_TEMPERATURE,
    CONF_CLOSE_DELAY,
    CONF_FROST_TEMPERATURE,
    CONF_IDLE_SENSORS,
    CONF_NOTIFY,
    CONF_ONLY_BELOW,
    CONF_OPEN_DELAY,
    CONF_OUTDOOR_SENSOR,
    CONF_REMIND_AFTER,
    CONF_ROOM_SENSOR,
    CONF_SCHEDULE,
    CONF_THERMOSTATS,
    CONF_WINDOWS,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_BOOST_TEMPERATURE,
    DEFAULT_CLOSE_DELAY_MINUTES,
    DEFAULT_FROST_TEMPERATURE,
    DEFAULT_OPEN_DELAY_SECONDS,
    DEFAULT_REMIND_AFTER_MINUTES,
    DOMAIN,
    MAX_TEMPERATURE,
    MIN_TEMPERATURE,
    SECTION_BOOST,
    SECTION_REMINDER,
    SECTION_WINDOW,
    SUBENTRY_ROOM,
    TITLE,
)

CONF_NAME = "name"


def _temperature(minimum: float = MIN_TEMPERATURE, maximum: float = MAX_TEMPERATURE) -> Any:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=0.5,
            unit_of_measurement="°C",
            mode=NumberSelectorMode.BOX,
        )
    )


def _house_schema(hass: HomeAssistant, options: Mapping[str, Any]) -> vol.Schema:
    boost = options.get(SECTION_BOOST, {})
    reminder = options.get(SECTION_REMINDER, {})
    notify = sorted(f"notify.{name}" for name in hass.services.async_services_for_domain("notify"))
    reminder_fields: dict[Any, Any] = {
        vol.Optional(
            CONF_OUTDOOR_SENSOR,
            description={"suggested_value": reminder.get(CONF_OUTDOOR_SENSOR)},
        ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="temperature")),
        vol.Optional(
            CONF_ONLY_BELOW, description={"suggested_value": reminder.get(CONF_ONLY_BELOW)}
        ): _temperature(-20, 30),
        vol.Optional(CONF_NOTIFY, default=reminder.get(CONF_NOTIFY, [])): SelectSelector(
            SelectSelectorConfig(
                options=notify, multiple=True, custom_value=True, mode=SelectSelectorMode.DROPDOWN
            )
        ),
    }
    return vol.Schema(
        {
            vol.Optional(
                CONF_IDLE_SENSORS, default=options.get(CONF_IDLE_SENSORS, [])
            ): EntitySelector(
                EntitySelectorConfig(domain=["input_boolean", "binary_sensor"], multiple=True)
            ),
            vol.Optional(
                CONF_FROST_TEMPERATURE,
                default=options.get(CONF_FROST_TEMPERATURE, DEFAULT_FROST_TEMPERATURE),
            ): _temperature(MIN_TEMPERATURE, 12),
            vol.Required(SECTION_BOOST): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_BOOST_TEMPERATURE,
                            default=boost.get(CONF_BOOST_TEMPERATURE, DEFAULT_BOOST_TEMPERATURE),
                        ): _temperature(),
                        vol.Optional(
                            CONF_BOOST_DURATION,
                            default=boost.get(
                                CONF_BOOST_DURATION, {"minutes": DEFAULT_BOOST_MINUTES}
                            ),
                        ): DurationSelector(DurationSelectorConfig()),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required(SECTION_REMINDER): section(
                vol.Schema(reminder_fields), {"collapsed": True}
            ),
        }
    )


class TadoXMatterProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance config flow: one house per Home Assistant."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the house settings; rooms are added afterwards as subentries."""
        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={}, options=user_input)
        return self.async_show_form(step_id="user", data_schema=_house_schema(self.hass, {}))

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: ConfigEntry) -> HouseOptionsFlow:
        """Return the options flow for the house settings."""
        return HouseOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,  # noqa: ARG003 – the same for every entry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Rooms are subentries."""
        return {SUBENTRY_ROOM: RoomSubentryFlow}


class HouseOptionsFlow(OptionsFlow):
    """Change the house settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and save the house settings."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_house_schema(self.hass, self.config_entry.options)
        )


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or change a room: thermostats, schedule, windows, room sensor, delays."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add a room."""
        return await self._async_room_step("user", user_input, {})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a room."""
        subentry = self._get_reconfigure_subentry()
        current = {**subentry.data, CONF_NAME: subentry.title}
        return await self._async_room_step("reconfigure", user_input, current)

    async def _async_room_step(
        self, step_id: str, user_input: dict[str, Any] | None, current: Mapping[str, Any]
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input, step_id)
            if not errors:
                name = (user_input.pop(CONF_NAME, "") or "").strip() or self._default_name(
                    user_input[CONF_THERMOSTATS]
                )
                if step_id == "reconfigure":
                    return self.async_update_and_abort(
                        self._get_entry(),
                        self._get_reconfigure_subentry(),
                        title=name,
                        data=user_input,
                    )
                return self.async_create_entry(title=name, data=user_input)
            current = user_input
        return self.async_show_form(
            step_id=step_id, data_schema=_room_schema(current), errors=errors
        )

    def _validate(self, user_input: Mapping[str, Any], step_id: str) -> dict[str, str]:
        thermostats = set(user_input.get(CONF_THERMOSTATS, []))
        if not thermostats:
            return {CONF_THERMOSTATS: "no_thermostats"}
        own = self._get_reconfigure_subentry().subentry_id if step_id == "reconfigure" else None
        for subentry in self._get_entry().subentries.values():
            if subentry.subentry_id == own:
                continue
            if thermostats & set(subentry.data.get(CONF_THERMOSTATS, [])):
                return {CONF_THERMOSTATS: "thermostat_in_other_room"}
        return {}

    def _default_name(self, thermostats: list[str]) -> str:
        """Name the room after the area of the first thermostat, else after the thermostat."""
        entity_id = thermostats[0]
        entry = er.async_get(self.hass).async_get(entity_id)
        area_id = entry.area_id if entry else None
        if entry and area_id is None and entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            area_id = device.area_id if device else None
        if area_id and (area := ar.async_get(self.hass).async_get_area(area_id)):
            return area.name
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id


def _room_schema(current: Mapping[str, Any]) -> vol.Schema:
    window = current.get(SECTION_WINDOW, {})

    def suggested(key: str) -> dict[str, Any]:
        return {"suggested_value": current.get(key)}

    return vol.Schema(
        {
            vol.Optional(CONF_NAME, description=suggested(CONF_NAME)): TextSelector(),
            vol.Required(CONF_THERMOSTATS, description=suggested(CONF_THERMOSTATS)): (
                EntitySelector(EntitySelectorConfig(domain="climate", multiple=True))
            ),
            vol.Required(CONF_SCHEDULE, description=suggested(CONF_SCHEDULE)): EntitySelector(
                EntitySelectorConfig(domain="schedule")
            ),
            vol.Optional(CONF_WINDOWS, default=list(current.get(CONF_WINDOWS, []))): (
                EntitySelector(EntitySelectorConfig(domain="binary_sensor", multiple=True))
            ),
            vol.Optional(CONF_ROOM_SENSOR, description=suggested(CONF_ROOM_SENSOR)): (
                EntitySelector(EntitySelectorConfig(domain="sensor", device_class="temperature"))
            ),
            vol.Required(SECTION_WINDOW): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_OPEN_DELAY,
                            default=window.get(
                                CONF_OPEN_DELAY, {"seconds": DEFAULT_OPEN_DELAY_SECONDS}
                            ),
                        ): DurationSelector(DurationSelectorConfig(enable_second=True)),
                        vol.Optional(
                            CONF_CLOSE_DELAY,
                            default=window.get(
                                CONF_CLOSE_DELAY, {"minutes": DEFAULT_CLOSE_DELAY_MINUTES}
                            ),
                        ): DurationSelector(DurationSelectorConfig(enable_second=True)),
                        vol.Optional(
                            CONF_REMIND_AFTER,
                            default=window.get(CONF_REMIND_AFTER, DEFAULT_REMIND_AFTER_MINUTES),
                        ): NumberSelector(
                            NumberSelectorConfig(
                                min=0,
                                max=720,
                                step=5,
                                unit_of_measurement="min",
                                mode=NumberSelectorMode.BOX,
                            )
                        ),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )
