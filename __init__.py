# HomeStral package initialization
__version__ = "0.1.0"

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .api_control import async_setup_api_control

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the HomeStral integration."""
    await async_setup_api_control(hass)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up HomeStral from a config entry."""
    try:
        from mistralai import Mistral  # PyPI standard install
    except ImportError:
        from mistralai.client import Mistral  # HA musllinux wheel (namespace package)
    entry.runtime_data = Mistral(api_key=entry.data["api_key"])
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "conversation", "stt", "tts"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, ["sensor", "conversation", "stt", "tts"])