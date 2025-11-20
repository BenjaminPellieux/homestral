from mistralai import Mistral
import voluptuous as vol
from .const import *


from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import (
    HomeAssistant,
    SupportsResponse,
)
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
)

from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import (
    config_validation as cv,
    selector,
)


from homeassistant.const  import Platform


import logging


_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.CONVERSATION, Platform.STT]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Homestral component."""
    _LOGGER.info("Initialisation du plugin Homestral")

    async def send_prompt(call):
        """Send a prompt to Mistral and return the response."""
        entry_id = call.data["config_entry"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_config_entry",
                translation_placeholders={"config_entry": entry_id},
            )
        client: Mistral = entry.runtime_data
        try:
            response = await client.chat.complete(
                model=entry.data.get(DEFAULT_CHAT_MODEL),
                messages=[{"role": "user", "content": call.data["prompt"]}],
            )
        except Exception as err:
            raise HomeAssistantError(f"Error generating content: {err}") from err
        return {"text": response.choices[0].message.content}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_CONTENT,
        send_prompt,
        schema=vol.Schema({
            vol.Required("config_entry"): selector.ConfigEntrySelector({
                "integration": DOMAIN,
            }),
            vol.Required("prompt"): cv.string,
        }),
        supports_response=SupportsResponse.ONLY,
    )

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Homestral from a config entry."""
    client = Mistral(api_key=entry.data[CONF_API_KEY])
    entry.runtime_data = client
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Homestral."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
