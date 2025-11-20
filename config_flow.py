from homeassistant import config_entries
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResult
import logging

from .const import *

_LOGGER = logging.getLogger(__name__)



class HomestralConfigFlow(config_entries.ConfigFlow, domain="homestral"):
    VERSION = 1

    async def async_step_user(
        self, user_input=None
    ) -> FlowResult:
        _LOGGER.info(f"user info : {user_input}")
        if user_input is not None:
            return self.async_create_entry(title="Homestral", data=user_input) # type: ignore
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
                vol.Optional(CONF_USE_AGENT, default=False): bool,
                vol.Optional(CONF_AGENT_ID, default=""): str, # type: ignore
                vol.Optional(CONF_MODEL, default=DEFAULT_CHAT_MODEL): str,
                vol.Optional(CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS): int,
                vol.Optional(CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE): float,
                vol.Optional(CONF_TOP_P, default=DEFAULT_TOP_P): float,
            })
        )
