"""Config flow for HomeStral."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import llm

from .const import (
    AVAILABLE_CHAT_MODELS,
    CONF_AGENT_ID,
    CONF_API_KEY,
    CONF_LEGACY_TOOLS,
    CONF_LLM_HASS_API,
    CONF_MAX_TOOL_ITERATIONS,
    CONF_MODEL,
    CONF_PROMPT,
    CONF_STT_BATCH_MODEL,
    CONF_STT_BIAS_ENTITIES,
    CONF_STT_CHAT_FALLBACK,
    CONF_STT_CUSTOM_VOCABULARY,
    CONF_STT_LANGUAGE,
    CONF_STT_MODE,
    CONF_STT_STREAMING_DELAY_MS,
    CONF_STT_TURN_DETECTION,
    CONF_TTS_DEFAULT_EMOTION,
    CONF_TTS_DEFAULT_PACE,
    CONF_TTS_EXPRESSIVENESS,
    CONF_TTS_VOICE,
    CONF_USE_AGENT,
    DEFAULT_CHAT_MODEL,
    DEFAULT_LEGACY_TOOLS,
    DEFAULT_LLM_HASS_API,
    DEFAULT_MAX_TOOL_ITERATIONS,
    DEFAULT_NAME,
    DEFAULT_PROMPT,
    DEFAULT_STT_BATCH_MODEL,
    DEFAULT_STT_BIAS_ENTITIES,
    DEFAULT_STT_CHAT_FALLBACK,
    DEFAULT_STT_CUSTOM_VOCABULARY,
    DEFAULT_STT_LANGUAGE,
    DEFAULT_STT_MODE,
    DEFAULT_STT_STREAMING_DELAY_MS,
    DEFAULT_STT_TURN_DETECTION,
    DEFAULT_TTS_EMOTION,
    DEFAULT_TTS_EXPRESSIVENESS,
    DEFAULT_TTS_PACE,
    DEFAULT_TTS_VOICE,
    DOMAIN,
    MAX_TOOL_ITERATIONS,
    MAX_TTS_EXPRESSIVENESS,
    MIN_TOOL_ITERATIONS,
    MIN_TTS_EXPRESSIVENESS,
    STT_BATCH_MODELS,
    STT_LANGUAGE_CHOICES,
    STT_MODES,
    STT_STREAMING_DELAY_CHOICES,
    STT_TURN_DETECTION_CHOICES,
    TTS_EMOTIONS,
    TTS_NONE,
    TTS_PACES,
    resolve_chat_model,
)
from .helpers import create_mistral_client

_LOGGER = logging.getLogger(__name__)


class InvalidAuth(Exception):
    """The API key was rejected by Mistral."""


class CannotConnect(Exception):
    """Mistral could not be reached."""


def _chat_options_schema(defaults: Mapping[str, Any], api_ids: list[str] | None = None) -> dict:
    return {
        vol.Optional(CONF_USE_AGENT, default=defaults.get(CONF_USE_AGENT, False)): bool,
        vol.Optional(CONF_AGENT_ID, default=defaults.get(CONF_AGENT_ID, "")): str,
        # Entries created by earlier releases may hold a model id that is no longer offered.
        vol.Optional(CONF_MODEL, default=resolve_chat_model(defaults.get(CONF_MODEL, DEFAULT_CHAT_MODEL))): vol.In(
            AVAILABLE_CHAT_MODELS
        ),
        vol.Optional(
            CONF_MAX_TOOL_ITERATIONS,
            default=defaults.get(CONF_MAX_TOOL_ITERATIONS, DEFAULT_MAX_TOOL_ITERATIONS),
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_TOOL_ITERATIONS, max=MAX_TOOL_ITERATIONS)),
        vol.Optional(
            CONF_LLM_HASS_API, default=defaults.get(CONF_LLM_HASS_API, list(DEFAULT_LLM_HASS_API))
        ): cv.multi_select({api: api for api in sorted(api_ids or DEFAULT_LLM_HASS_API)}),
        vol.Optional(CONF_LEGACY_TOOLS, default=defaults.get(CONF_LEGACY_TOOLS, DEFAULT_LEGACY_TOOLS)): bool,
        vol.Optional(CONF_PROMPT, default=defaults.get(CONF_PROMPT, DEFAULT_PROMPT)): str,
    }


def _stt_options_schema(defaults: Mapping[str, Any]) -> dict:
    return {
        vol.Optional(CONF_STT_MODE, default=defaults.get(CONF_STT_MODE, DEFAULT_STT_MODE)): vol.In(STT_MODES),
        vol.Optional(
            CONF_STT_TURN_DETECTION, default=defaults.get(CONF_STT_TURN_DETECTION, DEFAULT_STT_TURN_DETECTION)
        ): vol.In(STT_TURN_DETECTION_CHOICES),
        vol.Optional(
            CONF_STT_STREAMING_DELAY_MS,
            default=defaults.get(CONF_STT_STREAMING_DELAY_MS, DEFAULT_STT_STREAMING_DELAY_MS),
        ): vol.All(vol.Coerce(int), vol.In(STT_STREAMING_DELAY_CHOICES)),
        vol.Optional(CONF_STT_LANGUAGE, default=defaults.get(CONF_STT_LANGUAGE, DEFAULT_STT_LANGUAGE)): vol.In(
            STT_LANGUAGE_CHOICES
        ),
        vol.Optional(CONF_STT_BATCH_MODEL, default=defaults.get(CONF_STT_BATCH_MODEL, DEFAULT_STT_BATCH_MODEL)): vol.In(
            list(STT_BATCH_MODELS)
        ),
        vol.Optional(
            CONF_STT_CUSTOM_VOCABULARY,
            default=defaults.get(CONF_STT_CUSTOM_VOCABULARY, DEFAULT_STT_CUSTOM_VOCABULARY),
        ): str,
        vol.Optional(
            CONF_STT_BIAS_ENTITIES, default=defaults.get(CONF_STT_BIAS_ENTITIES, DEFAULT_STT_BIAS_ENTITIES)
        ): bool,
        vol.Optional(
            CONF_STT_CHAT_FALLBACK, default=defaults.get(CONF_STT_CHAT_FALLBACK, DEFAULT_STT_CHAT_FALLBACK)
        ): bool,
    }


def _tts_options_schema(defaults: Mapping[str, Any]) -> dict:
    return {
        vol.Optional(CONF_TTS_VOICE, default=defaults.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE)): str,
        vol.Optional(
            CONF_TTS_DEFAULT_EMOTION, default=defaults.get(CONF_TTS_DEFAULT_EMOTION, DEFAULT_TTS_EMOTION)
        ): vol.In([TTS_NONE, *TTS_EMOTIONS]),
        vol.Optional(CONF_TTS_DEFAULT_PACE, default=defaults.get(CONF_TTS_DEFAULT_PACE, DEFAULT_TTS_PACE)): vol.In(
            [TTS_NONE, *TTS_PACES]
        ),
        # 0 keeps the service default; otherwise the documented 1.0 to 5.0 range.
        vol.Optional(
            CONF_TTS_EXPRESSIVENESS, default=defaults.get(CONF_TTS_EXPRESSIVENESS, DEFAULT_TTS_EXPRESSIVENESS)
        ): vol.All(
            vol.Coerce(float),
            vol.Any(
                DEFAULT_TTS_EXPRESSIVENESS,
                vol.Range(min=MIN_TTS_EXPRESSIVENESS, max=MAX_TTS_EXPRESSIVENESS),
            ),
        ),
    }


def _options_schema(defaults: Mapping[str, Any], api_ids: list[str] | None = None) -> vol.Schema:
    return vol.Schema(
        {
            **_chat_options_schema(defaults, api_ids),
            **_stt_options_schema(defaults),
            **_tts_options_schema(defaults),
        }
    )


# The initial form asks for the key and the chat settings only; STT settings live in the options flow.
USER_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str, **_chat_options_schema({})})


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

    VERSION = 2

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
    """Let the user change model, agent, tool-loop and speech-to-text settings after setup."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        api_ids = [api.id for api in llm.async_get_apis(self.hass)]
        return self.async_show_form(step_id="init", data_schema=_options_schema(current, api_ids))
