"""HomeStral — Mistral AI conversation, speech-to-text and text-to-speech for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .agent import HomestralRuntime, MistralTurnRunner
from .api_control import async_setup_api_control
from .const import (
    CONF_API_KEY,
    CONF_LEGACY_TOOLS,
    CONF_LLM_HASS_API,
    DEFAULT_LLM_HASS_API,
    DOMAIN,
    PLATFORMS,
)
from .helpers import create_mistral_client, install_custom_sentences
from .intent import async_setup_intents

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services and intents (independent of config entries)."""
    await async_setup_api_control(hass)
    await async_setup_intents(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HomeStral from a config entry."""
    # The client constructor does blocking importlib.metadata scans — build it in an executor.
    client = await hass.async_add_executor_job(create_mistral_client, entry.data[CONF_API_KEY])
    # One client and one turn runner shared by the conversation, intent, STT and TTS entities.
    entry.runtime_data = HomestralRuntime(client=client, runner=MistralTurnRunner(hass, entry, client))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    installed = await hass.async_add_executor_job(install_custom_sentences, hass.config.path("custom_sentences"))
    if installed:
        await hass.services.async_call("conversation", "reload", blocking=True)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an older config entry.

    Version 1 entries predate the Home Assistant LLM API: the model acted through
    HomeStral's own tools, which bypass the "exposed to Assist" setting. They keep
    those tools so nothing breaks on upgrade, alongside the Assist API; new installs
    use the Assist API alone.
    """
    if entry.version > 2:
        # Downgrade from a future version is not supported.
        return False

    if entry.version == 1:
        options = {
            **entry.options,
            CONF_LLM_HASS_API: entry.options.get(CONF_LLM_HASS_API, list(DEFAULT_LLM_HASS_API)),
            CONF_LEGACY_TOOLS: entry.options.get(CONF_LEGACY_TOOLS, True),
        }
        hass.config_entries.async_update_entry(entry, options=options, version=2)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
