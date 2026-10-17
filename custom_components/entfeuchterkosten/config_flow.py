"""Config flow: the dialog shown under Settings > Devices & services."""

from __future__ import annotations

from typing import Any

# Home Assistant 2026.9+ validates with "probatio" instead of "voluptuous".
import probatio as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_NAME,
    CONF_POWER_ENTITY,
    CONF_PRICE,
    CONF_SOLAR_ENTITY,
    DEFAULT_NAME,
    DEFAULT_PRICE,
    DOMAIN,
    MAX_PRICE,
)

_POWER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.POWER)
)


def _power_settings(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return the power sensors and the price from the dialog."""
    return {
        CONF_POWER_ENTITY: user_input[CONF_POWER_ENTITY],
        # Stored also when empty, so an option can remove a sensor set up before.
        CONF_SOLAR_ENTITY: user_input.get(CONF_SOLAR_ENTITY) or None,
        CONF_PRICE: float(user_input[CONF_PRICE]),
    }


def _check(settings: dict[str, Any]) -> dict[str, str]:
    """Return the errors of the dialog, if any."""
    if settings[CONF_SOLAR_ENTITY] == settings[CONF_POWER_ENTITY]:
        return {CONF_SOLAR_ENTITY: "same_entity"}
    return {}


def _price_selector(currency: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=MAX_PRICE,
            # Home Assistant allows no step below 0.001; prices often have 4 decimals.
            step="any",
            unit_of_measurement=f"{currency}/kWh",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


class EntfeuchterkostenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a name, the power sensors and the electricity price."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(
                {CONF_POWER_ENTITY: user_input[CONF_POWER_ENTITY]}
            )
            settings = _power_settings(user_input)
            errors = _check(settings)
            if not errors:
                name = user_input[CONF_NAME].strip() or DEFAULT_NAME
                return self.async_create_entry(
                    title=name, data={CONF_NAME: name, **settings}
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                vol.Required(CONF_POWER_ENTITY): _POWER_SELECTOR,
                vol.Optional(CONF_SOLAR_ENTITY): _POWER_SELECTOR,
                vol.Required(CONF_PRICE, default=DEFAULT_PRICE): _price_selector(
                    self.hass.config.currency
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow (the "Configure" button)."""
        return EntfeuchterkostenOptionsFlow()


class EntfeuchterkostenOptionsFlow(OptionsFlow):
    """Change the power sensors and the electricity price after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            settings = _power_settings(user_input)
            errors = _check(settings)
            if not errors:
                return self.async_create_entry(data=settings)

        schema = vol.Schema(
            {
                vol.Required(CONF_POWER_ENTITY): _POWER_SELECTOR,
                # Suggested, not a default: a default could not be cleared.
                vol.Optional(CONF_SOLAR_ENTITY): _POWER_SELECTOR,
                vol.Required(CONF_PRICE): _price_selector(self.hass.config.currency),
            }
        )
        suggested = user_input or {
            **self.config_entry.data,
            **self.config_entry.options,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )
