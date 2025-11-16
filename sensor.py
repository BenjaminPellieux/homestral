#sensor.py
from homeassistant.helpers.entity import Entity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
import logging
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up the Homestral sensor."""
    api_key = entry.data["api_key"]
    sensor = HomestralSensor(api_key)
    _LOGGER.info(f" setup entry : {sensor} : {api_key}")
    async_add_entities([sensor], True)

class HomestralSensor(Entity):
    def __init__(self, api_key):
        _LOGGER.info(f"HomeStral sensors : {api_key=}")
        self._api_key = api_key
        self._attr_name = "Homestral Sensor"
        self._attr_unique_id = "homestral_sensor"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "homestral")},
            "name": "Homestral Sensor",
            "manufacturer": "Homestral",
        }

    async def async_update(self):
        """Update the sensor data."""
        # Logique pour mettre à jour les données du capteur
        pass