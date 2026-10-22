"""
Intent handler for the HomestralQuery intent.

Voice entry point: a custom sentence such as "Demande à Homestral <free text>"
(shipped in custom_sentences/{fr,en}.yaml and installed into
<config>/custom_sentences/<lang>/ at setup) matches the HomestralQuery intent,
the free text is sent to the Mistral conversation through the shared turn
runner and the answer is spoken back.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import intent

from .agent import HomestralRuntime
from .const import DOMAIN
from .logging_config import get_logger

_LOGGER = get_logger(__name__)

INTENT_HOMESTRAL_QUERY = "HomestralQuery"


class HomestralQueryHandler(intent.IntentHandler):
    """Handle HomestralQuery intents: answer a free-text voice query."""

    intent_type = INTENT_HOMESTRAL_QUERY
    slot_schema = {"query": cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Send the query slot to the Mistral conversation and speak the answer."""
        query = (intent_obj.slots.get("query") or {}).get("value")
        if not query:
            return self._error_response(intent_obj, "Je n'ai pas compris la question.")

        entries = intent_obj.hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return self._error_response(intent_obj, "Homestral n'est pas configuré.")

        runtime: HomestralRuntime = entries[0].runtime_data
        try:
            _LOGGER.info("[INTENT] HomestralQuery one-shot turn")
            answer = await runtime.runner.async_answer(query, ha_conversation_id=None)
        except Exception:
            _LOGGER.exception("Error while handling HomestralQuery intent")
            return self._error_response(intent_obj, "Désolé, une erreur est survenue.")

        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        response.async_set_speech(answer)
        return response

    @staticmethod
    def _error_response(intent_obj: intent.Intent, message: str) -> intent.IntentResponse:
        """Build an error response — the handler must never raise."""
        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.ERROR
        response.async_set_speech(message)
        return response


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Set up the Homestral intents."""
    intent.async_register(hass, HomestralQueryHandler())
