"""
Intent handler for the HomestralQuery intent.

Voice entry point: a custom sentence such as "Demande à Homestral <free text>"
(shipped in custom_sentences/{fr,en}.yaml — to be copied into
<config>/custom_sentences/<lang>/) matches the HomestralQuery intent, the free
text is sent to the Mistral conversation and the answer is spoken back.
"""

import json

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import intent

try:
    from mistralai.models.toolexecutionentry import ToolExecutionEntry
    from mistralai.models.messageoutputentry import MessageOutputEntry
    from mistralai.models import FunctionCallEntry, FunctionResultEntry
except ImportError:
    # HA musllinux wheel uses mistralai.client.models (namespace package)
    from mistralai.client.models import (
        ToolExecutionEntry, MessageOutputEntry,
        FunctionCallEntry, FunctionResultEntry,
    )

from .const import (
    CONF_AGENT_ID,
    CONF_MAX_TOOL_ITERATIONS,
    CONF_MODEL,
    CONF_USE_AGENT,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOOL_ITERATIONS,
    DOMAIN,
    SERVICE_GENERATE_CONTENT,
)
from .conversation import _extract_text
from .logging_config import get_logger
from .tools import ALL_TOOLS, HAToolExecutor, build_ha_context

_LOGGER = get_logger(__name__)

INTENT_HOMESTRAL_QUERY = "HomestralQuery"

# Keys probed in the generate_content service response, in order of preference
SERVICE_RESPONSE_TEXT_KEYS = ("response", "text", "content", "answer")


class HomestralQueryHandler(intent.IntentHandler):
    """Handle HomestralQuery intents: answer a free-text voice query."""

    intent_type = INTENT_HOMESTRAL_QUERY
    slot_schema = {"query": cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Send the query slot to the Mistral conversation and speak the answer."""
        query = (intent_obj.slots.get("query") or {}).get("value")
        if not query:
            return self._error_response(
                intent_obj, "Je n'ai pas compris la question."
            )

        entries = intent_obj.hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return self._error_response(
                intent_obj, "Homestral n'est pas configuré."
            )

        try:
            answer = await self._async_get_answer(intent_obj.hass, entries[0], query)
        except Exception as exc:
            _LOGGER.exception("Error while handling HomestralQuery intent")
            return self._error_response(
                intent_obj, f"Désolé, une erreur est survenue : {exc}"
            )

        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        response.async_set_speech(answer)
        return response

    @staticmethod
    def _error_response(
        intent_obj: intent.Intent, message: str
    ) -> intent.IntentResponse:
        """Build an error response — the handler must never raise."""
        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.ERROR
        response.async_set_speech(message)
        return response

    async def _async_get_answer(
        self, hass: HomeAssistant, entry: ConfigEntry, query: str
    ) -> str:
        """Return the answer text for the query.

        Prefers the homestral.generate_content service; falls back to a direct
        Mistral conversation call (same pattern as conversation.py) when the
        service is unavailable or returns no text.
        """
        try:
            result = await hass.services.async_call(
                DOMAIN,
                SERVICE_GENERATE_CONTENT,
                {"config_entry": entry.entry_id, "prompt": query},
                blocking=True,
                return_response=True,
            )
        except Exception as exc:
            _LOGGER.warning(
                "generate_content service unavailable (%s) — "
                "falling back to direct Mistral conversation",
                exc,
            )
        else:
            if isinstance(result, dict):
                for key in SERVICE_RESPONSE_TEXT_KEYS:
                    value = result.get(key)
                    if isinstance(value, str) and value.strip():
                        return value
            _LOGGER.warning(
                "generate_content returned no usable text (%r) — "
                "falling back to direct Mistral conversation",
                result,
            )
        return await self._async_conversation_answer(hass, entry, query)

    async def _async_conversation_answer(
        self, hass: HomeAssistant, entry: ConfigEntry, query: str
    ) -> str:
        """Send the query to the Mistral conversation and return the answer text.

        Mirrors the tool loop of MistralConversationEntity: start a conversation
        with the HA tools, execute any FunctionCallEntry, and extract the final
        MessageOutputEntry text.
        """
        client = entry.runtime_data
        instructions = await build_ha_context(hass)
        kwargs = dict(
            inputs=query,
            instructions=instructions,
            tools=ALL_TOOLS,
        )
        if entry.data.get(CONF_USE_AGENT, False):
            _LOGGER.info("[INTENT] starting new conversation with agent")
            kwargs["agent_id"] = entry.data.get(CONF_AGENT_ID)
        else:
            _LOGGER.info("[INTENT] starting new conversation with model")
            kwargs["model"] = entry.data.get(CONF_MODEL, DEFAULT_CHAT_MODEL)

        response = await client.beta.conversations.start_async(**kwargs)
        conversation_id = getattr(response, "conversation_id", None)
        tool_executor = HAToolExecutor(hass)

        content = None
        # Same configurable tool-loop bound as conversation.py
        max_iterations = int(
            entry.data.get(CONF_MAX_TOOL_ITERATIONS, DEFAULT_MAX_TOOL_ITERATIONS)
        )
        for _iteration in range(max_iterations):
            if not response.outputs:
                content = "Désolé, je n'ai pas reçu de réponse."
                break

            first = response.outputs[0]

            if isinstance(first, ToolExecutionEntry):
                # Built-in Mistral server-side tool (web_search, code_interpreter, etc.)
                _LOGGER.info("[INTENT TOOL built-in] %s", first.name)
                for out in response.outputs[1:]:
                    if isinstance(out, MessageOutputEntry):
                        content = _extract_text(out.content)
                        break
                if content is None:
                    content = "La recherche n'a pas retourné de résultat."
                break

            if isinstance(first, FunctionCallEntry):
                # Collect ALL function calls — Mistral may batch several in one response.
                all_calls = [
                    o for o in response.outputs if isinstance(o, FunctionCallEntry)
                ]
                result_entries = []
                for call in all_calls:
                    args_str = (
                        call.arguments if isinstance(call.arguments, str)
                        else json.dumps(call.arguments)
                    )
                    _LOGGER.info("[INTENT TOOL custom] %s, args: %s", call.name, args_str)
                    try:
                        tool_result = await tool_executor.execute(
                            call.name,
                            json.loads(args_str or "{}"),
                        )
                    except Exception as exc:
                        _LOGGER.error("[INTENT TOOL error] %s: %s", call.name, exc)
                        tool_result = json.dumps({"error": str(exc)})
                    result_entries.append(FunctionResultEntry(
                        tool_call_id=call.tool_call_id,
                        result=tool_result,
                    ))
                response = await client.beta.conversations.append_async(
                    conversation_id=conversation_id,
                    inputs=result_entries,
                )
                conversation_id = getattr(
                    response, "conversation_id", conversation_id
                )
                continue

            if isinstance(first, MessageOutputEntry):
                content = _extract_text(first.content)
                break

            _LOGGER.warning(
                "[INTENT TOOL LOOP] unknown output type: %s", type(first).__name__
            )
            content = "Réponse inattendue du modèle."
            break
        else:
            content = "La réponse a nécessité trop d'étapes. Veuillez reformuler."

        return content or "Aucune réponse disponible."


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Set up the Homestral intents."""
    intent.async_register(hass, HomestralQueryHandler())
