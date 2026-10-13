# HomeStral package initialization
__version__ = "0.2.1"

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .api_control import async_setup_api_control

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the HomeStral integration."""
    await async_setup_api_control(hass)
    return True

def _create_mistral_client(api_key: str):
    """Create the Mistral client (blocking importlib.metadata scans — run in an executor)."""
    try:
        from mistralai import Mistral  # PyPI standard install
    except ImportError:
        from mistralai.client import Mistral  # HA musllinux wheel (namespace package)
    return Mistral(api_key=api_key)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up HomeStral from a config entry."""
    # The client constructor does blocking importlib.metadata scans —
    # build it in an executor to avoid blocking the event loop.
    entry.runtime_data = await hass.async_add_executor_job(
        _create_mistral_client, entry.data["api_key"]
    )
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "conversation", "stt", "tts"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, ["sensor", "conversation", "stt", "tts"])