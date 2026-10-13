import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up the Homestral sensor."""
    api_key = entry.data["api_key"]
    sensor = HomestralSensor(api_key)
    _LOGGER.info(f"Setup entry: {sensor.name}")
    async_add_entities([sensor], True)


class HomestralSensor(Entity):
    def __init__(self, api_key):
        _LOGGER.info("HomeStral sensor initialised")
        self._api_key = api_key

    @property
    def name(self):
        return "Homestral Sensor"

    @property
    def unique_id(self):
        return "homestral_sensor"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "homestral")},
            "name": "Homestral Sensor",
            "manufacturer": "Homestral",
        }
