from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationResult,
    ConversationInput,
    AbstractConversationAgent,
)


from homeassistant.components.conversation.chat_log import AssistantContent
import homeassistant.components.conversation as conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.const import MATCH_ALL
try:
    from mistralai.models.toolexecutionentry import ToolExecutionEntry
    from mistralai.models.messageoutputentry import MessageOutputEntry
    from mistralai.models import ConversationResponse
    from mistralai.models import FunctionCallEntry, FunctionResultEntry
except ImportError:
    # HA musllinux wheel uses mistralai.client.models (namespace package)
    from mistralai.client.models import (
        ToolExecutionEntry, MessageOutputEntry, ConversationResponse,
        FunctionCallEntry, FunctionResultEntry,
    )
from .const import *
import json
from .errors import ConversationError
from .logging_config import get_logger
from .tools import HAToolExecutor, ALL_TOOLS, build_ha_context, MISTRAL_BUILTIN_TOOLS


_LOGGER = get_logger(__name__)


def _extract_text(content) -> str:
    """Extract plain text from a Mistral content field.

    Handles str, list[TextChunk], and mixed lists that may contain ToolReference
    objects (web_search citations). Only TextChunk items (type='text') are kept.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for chunk in content:
            chunk_type = getattr(chunk, "type", None)
            if chunk_type == "text" or (chunk_type is None and hasattr(chunk, "text")):
                parts.append(chunk.text)
            # ToolReference (type='tool_reference') and other non-text chunks are skipped
        return "".join(parts)
    return str(content)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Mistral conversation entity."""
    async_add_entities([MistralConversationEntity(hass, entry)])

class MistralConversationEntity(
    ConversationEntity,
    AbstractConversationAgent,
):
    """Mistral conversation entity."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the conversation entity."""
        super().__init__()
        self.hass = hass
        self._entry = entry
        self._client = entry.runtime_data
        self._attr_name = "Mistral Conversation"
        self._attr_unique_id = entry.entry_id
        self._conversation_id = None
        self._tool_executor = HAToolExecutor(hass)

    @property
    def supported_languages(self):
        """Return a list of supported languages."""
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self._entry, self)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        conversation.async_unset_agent(self.hass, self._entry)
        await super().async_will_remove_from_hass()

    async def async_handle_error(self, chat_log, error):
        """Handle errors and append error messages to the chat log."""
        error_message = f"Error: {str(error)}"
        if hasattr(error, 'code'):
            error_message += f" (Code: {error.code})"
        if hasattr(error, 'details'):
            error_message += f" Details: {error.details}"
        chat_log.content.append(AssistantContent(
            agent_id=self._attr_unique_id,
            content=error_message,
        ))

    async def start_conversation(self, user_input: ConversationInput) -> ConversationResponse:
        instructions = await build_ha_context(self.hass)
        kwargs = dict(
            inputs=user_input.text,
            instructions=instructions,
            tools=ALL_TOOLS,
        )
        if self._entry.data.get(CONF_USE_AGENT, False):
            _LOGGER.info("Starting new conversation with agent")
            kwargs["agent_id"] = self._entry.data.get(CONF_AGENT_ID)
        else:
            _LOGGER.info("Starting new conversation with model")
            kwargs["model"] = self._entry.data.get(CONF_MODEL, DEFAULT_CHAT_MODEL)
        return await self._client.beta.conversations.start_async(**kwargs)

    async def keep_conversation(self, user_input: ConversationInput) -> ConversationResponse:
        _LOGGER.info("Continuing conversation")
        instructions = await build_ha_context(self.hass)
        return await self._client.beta.conversations.append_async(
            conversation_id=self._conversation_id,
            inputs=user_input.text,
            completion_args={"instructions": instructions},
        )



    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log,
    ) -> ConversationResult:
        """Process the user input and call the API."""
        _LOGGER.info(f"[CONV] new message, conversation_id={self._conversation_id!r}")
        try:
            if self._conversation_id is None:
                response = await self.start_conversation(user_input)
            else:
                response = await self.keep_conversation(user_input)
                  
            # Tool execution loop (max 5 iterations)
            self._conversation_id = getattr(response, "conversation_id", None)
            content = None
            for iteration in range(5):
                if not response.outputs:
                    content = "Désolé, je n'ai pas reçu de réponse."
                    break

                first = response.outputs[0]
                _LOGGER.info(f"[TOOL LOOP iter={iteration}] output type: {type(first).__name__}")

                if isinstance(first, ToolExecutionEntry):
                    # Built-in Mistral server-side tool (web_search, code_interpreter, etc.)
                    tool_name = str(first.name)
                    _LOGGER.info(f"[TOOL built-in] {tool_name}, args: {first.arguments}")
                    for out in response.outputs[1:]:
                        if isinstance(out, MessageOutputEntry):
                            content = _extract_text(out.content)
                            break
                    if content is None:
                        content = "La recherche n'a pas retourné de résultat."
                    break

                elif isinstance(first, FunctionCallEntry):
                    # Custom HA FunctionTool — exécuté côté client
                    tool_name = first.name
                    raw_args = first.arguments
                    args_str = raw_args if isinstance(raw_args, str) else json.dumps(raw_args)
                    _LOGGER.info(f"[TOOL custom] {tool_name}, args: {args_str}")

                    tool_result = await self._tool_executor.execute(
                        tool_name,
                        json.loads(args_str or "{}"),
                    )
                    _LOGGER.info(f"[TOOL result] {tool_result[:200]}")

                    result_entry = FunctionResultEntry(
                        tool_call_id=first.tool_call_id,
                        result=tool_result,
                    )
                    response = await self._client.beta.conversations.append_async(
                        conversation_id=self._conversation_id,
                        inputs=[result_entry],
                    )
                    self._conversation_id = getattr(response, "conversation_id", self._conversation_id)

                elif isinstance(first, MessageOutputEntry):
                    content = _extract_text(first.content)
                    break
                else:
                    _LOGGER.warning(f"[TOOL LOOP] unknown output type: {type(first)}")
                    content = "Réponse inattendue du modèle."
                    break
            else:
                content = "La réponse a nécessité trop d'étapes. Veuillez reformuler."

            if content is None:
                content = "Aucune réponse disponible."

            content = _extract_text(content) if content is not None else "Aucune réponse."
            _LOGGER.info(f"[CONV] final content: {content[:200]}")
            chat_log.content.append(AssistantContent(
                agent_id=self._attr_unique_id,
                content=content, 
            ))

        except Exception as e:
            error = ConversationError(
                message=f"Error processing conversation: {e}",
                code="CONVERSATION_PROCESSING_ERROR",
                details={"error": str(e), "conversation_id": self._conversation_id}
            )
            _LOGGER.error(f"Error processing conversation: {error}")
            await self.async_handle_error(chat_log, error)
            self._conversation_id = None

        return conversation.async_get_result_from_chat_log(user_input, chat_log)
