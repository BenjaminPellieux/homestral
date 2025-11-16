# __init__.py
from mistralai import Mistral
import os
import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import Platform
import logging
import asyncio
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)



async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Homestral component."""
    _LOGGER.info("Initialisation du plugin Homestral")

    async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
        """Set up the Homestral component."""
        _LOGGER.info("Initialisation du plugin Homestral")

        # Enregistrer un service pour recharger le plugin
        async def reload_service(call):
            """Service to reload the Homestral plugin."""
            _LOGGER.info("Rechargement du plugin Homestral")
            # Logique pour recharger le plugin
            # Par exemple, recharger la configuration ou les données
            await hass.config_entries.async_reload(entry.entry_id)

        hass.services.async_register(DOMAIN, "reload", reload_service)

        return True

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Homestral from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    )
    return True
