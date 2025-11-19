from homeassistant import config_entries
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResult
import logging

_LOGGER = logging.getLogger(__name__)

class HomestralConfigFlow(config_entries.ConfigFlow, domain="homestral"):
    VERSION = 1

    async def async_step_user(
        self, user_input=None
    ) -> FlowResult:
        _LOGGER.info(f"user info : {user_input}")
        if user_input is not None:
            return self.async_create_entry(title="Homestral", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_key"): str,
            })
        )
