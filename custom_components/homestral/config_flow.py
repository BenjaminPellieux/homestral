"""Config flow for HomeStral."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import (
    AVAILABLE_CHAT_MODELS,
    CONF_AGENT_ID,
    CONF_API_KEY,
    CONF_MAX_TOOL_ITERATIONS,
    CONF_MODEL,
    CONF_USE_AGENT,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOOL_ITERATIONS,
    DEFAULT_NAME,
    DOMAIN,
    MAX_TOOL_ITERATIONS,
    MIN_TOOL_ITERATIONS,
)
from .helpers import create_mistral_client

_LOGGER = logging.getLogger(__name__)


class InvalidAuth(Exception):
    """The API key was rejected by Mistral."""


class CannotConnect(Exception):
    """Mistral could not be reached."""


def _options_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_USE_AGENT, default=defaults.get(CONF_USE_AGENT, False)): bool,
            vol.Optional(CONF_AGENT_ID, default=defaults.get(CONF_AGENT_ID, "")): str,
            vol.Optional(CONF_MODEL, default=defaults.get(CONF_MODEL, DEFAULT_CHAT_MODEL)): vol.In(
                AVAILABLE_CHAT_MODELS
            ),
            vol.Optional(
                CONF_MAX_TOOL_ITERATIONS,
                default=defaults.get(CONF_MAX_TOOL_ITERATIONS, DEFAULT_MAX_TOOL_ITERATIONS),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_TOOL_ITERATIONS, max=MAX_TOOL_ITERATIONS)),
        }
    )


USER_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str}).extend(_options_schema({}).schema)


def _validate_api_key(api_key: str) -> None:
    """Check the key against the Mistral API (blocking — run in an executor)."""
    client = create_mistral_client(api_key)
    try:
        client.models.list()
    except Exception as exc:
        if getattr(exc, "status_code", None) in (401, 403):
            raise InvalidAuth from exc
        raise CannotConnect from exc


class HomestralConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial HomeStral setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            try:
                await self.hass.async_add_executor_job(_validate_api_key, api_key)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while validating the Mistral API key")
                errors["base"] = "unknown"
            else:
                options = {key: value for key, value in user_input.items() if key != CONF_API_KEY}
                return self.async_create_entry(title=DEFAULT_NAME, data={CONF_API_KEY: api_key}, options=options)

        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HomestralOptionsFlow:
        return HomestralOptionsFlow()


class HomestralOptionsFlow(OptionsFlow):
    """Let the user change model and agent settings after setup."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_options_schema(current))
