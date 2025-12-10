# HomeStral package initialization
__version__ = "0.0.2"

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .api_control import async_setup_api_control

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the HomeStral integration."""
    # Setup API control service
    await async_setup_api_control(hass)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up HomeStral from a config entry."""
    # Forward the setup to the sensor and other platforms
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, ["sensor", "conversation", "stt"])
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # Unload all platforms
    await hass.config_entries.async_unload_platforms(entry, ["sensor", "conversation", "stt"])
    return True