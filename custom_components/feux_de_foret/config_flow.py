"""Config flow for Feux de forêt integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEBUG_LOGGING,
    CONF_ENABLE_PERSISTENT_NOTIFICATIONS,
    CONF_ENABLE_TELEGRAM_NOTIFICATIONS,
    CONF_NAME,
    CONF_NOTIFICATION_MAX_DISTANCE_KM,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    CONF_TELEGRAM_NOTIFY_SERVICE,
    DEFAULT_DEBUG_LOGGING,
    DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS,
    DEFAULT_ENABLE_TELEGRAM_NOTIFICATIONS,
    DEFAULT_NAME,
    DEFAULT_NOTIFICATION_MAX_DISTANCE_KM,
    DEFAULT_RADIUS_KM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TELEGRAM_NOTIFY_SERVICE,
    DOMAIN,
)


class FeuxDeForetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            zone_name = user_input.get(CONF_NAME) or DEFAULT_NAME
            return self.async_create_entry(
                title=f"{zone_name} ({user_input[CONF_RADIUS]} km)",
                data=user_input,
            )

        default_lat = self.hass.config.latitude
        default_lng = self.hass.config.longitude

        schema = vol.Schema({
            vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
            vol.Required(CONF_LATITUDE, default=default_lat): vol.Coerce(float),
            vol.Required(CONF_LONGITUDE, default=default_lng): vol.Coerce(float),
            vol.Required(CONF_RADIUS, default=DEFAULT_RADIUS_KM): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=500, step=1,
                    mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="km")
            ),
            vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=60, step=1,
                    mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="min")
            ),
            vol.Required(CONF_ENABLE_PERSISTENT_NOTIFICATIONS,
                default=DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS): bool,
            vol.Required(CONF_ENABLE_TELEGRAM_NOTIFICATIONS,
                default=DEFAULT_ENABLE_TELEGRAM_NOTIFICATIONS): bool,
            vol.Optional(CONF_TELEGRAM_NOTIFY_SERVICE,
                default=DEFAULT_TELEGRAM_NOTIFY_SERVICE): str,
            vol.Required(CONF_DEBUG_LOGGING, default=DEFAULT_DEBUG_LOGGING): bool,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return FeuxDeForetOptionsFlow()


class FeuxDeForetOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            telegram_enabled = user_input.get(CONF_ENABLE_TELEGRAM_NOTIFICATIONS)
            telegram_service = str(user_input.get(CONF_TELEGRAM_NOTIFY_SERVICE, "")).strip()
            if telegram_enabled and not telegram_service:
                errors[CONF_TELEGRAM_NOTIFY_SERVICE] = "telegram_service_required"
            if not errors:
                user_input[CONF_TELEGRAM_NOTIFY_SERVICE] = telegram_service
                return self.async_create_entry(title="", data=user_input)

        defaults = {**self.config_entry.data, **self.config_entry.options}
        current_radius = defaults.get(CONF_RADIUS, DEFAULT_RADIUS_KM)
        current_interval = defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        current_name = defaults.get(CONF_NAME, DEFAULT_NAME)
        current_max_distance = defaults.get(CONF_NOTIFICATION_MAX_DISTANCE_KM, DEFAULT_NOTIFICATION_MAX_DISTANCE_KM)

        schema = vol.Schema({
            vol.Required(CONF_NAME, default=current_name): str,
            vol.Required(CONF_RADIUS, default=current_radius): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=500, step=1,
                    mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="km")
            ),
            vol.Required(CONF_SCAN_INTERVAL, default=current_interval): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=60, step=1,
                    mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="min")
            ),
            vol.Required(CONF_ENABLE_PERSISTENT_NOTIFICATIONS,
                default=defaults.get(CONF_ENABLE_PERSISTENT_NOTIFICATIONS, DEFAULT_ENABLE_PERSISTENT_NOTIFICATIONS)): bool,
            vol.Optional(CONF_NOTIFICATION_MAX_DISTANCE_KM, default=current_max_distance): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=500, step=1,
                    mode=selector.NumberSelectorMode.SLIDER, unit_of_measurement="km")
            ),
            vol.Required(CONF_ENABLE_TELEGRAM_NOTIFICATIONS,
                default=defaults.get(CONF_ENABLE_TELEGRAM_NOTIFICATIONS, DEFAULT_ENABLE_TELEGRAM_NOTIFICATIONS)): bool,
            vol.Optional(CONF_TELEGRAM_NOTIFY_SERVICE,
                default=defaults.get(CONF_TELEGRAM_NOTIFY_SERVICE, DEFAULT_TELEGRAM_NOTIFY_SERVICE)): str,
            vol.Required(CONF_DEBUG_LOGGING,
                default=defaults.get(CONF_DEBUG_LOGGING, DEFAULT_DEBUG_LOGGING)): bool,
        })
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)