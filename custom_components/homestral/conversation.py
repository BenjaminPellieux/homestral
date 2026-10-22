"""Mistral conversation entity: Home Assistant plumbing around the shared turn runner."""

from __future__ import annotations

import homeassistant.components.conversation as conversation
from homeassistant.components.conversation import (
    AbstractConversationAgent,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.components.conversation.chat_log import AssistantContent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .agent import HomestralRuntime, extract_text
from .errors import ConversationError
from .logging_config import get_logger

_LOGGER = get_logger(__name__)

# Kept for callers that imported the helper from this module.
_extract_text = extract_text


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

    # The answer is pushed into the chat log as it is generated, so the Assist pipeline can
    # start speaking before the model has finished writing.
    _attr_supports_streaming = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the conversation entity."""
        super().__init__()
        self.hass = hass
        self._entry = entry
        runtime: HomestralRuntime = entry.runtime_data
        self._runner = runtime.runner
        self._client = runtime.client
        self._attr_name = "Mistral Conversation"
        self._attr_unique_id = entry.entry_id

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
        if hasattr(error, "code"):
            error_message += f" (Code: {error.code})"
        if hasattr(error, "details"):
            error_message += f" Details: {error.details}"
        chat_log.content.append(
            AssistantContent(
                agent_id=self._attr_unique_id,
                content=error_message,
            )
        )

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log,
    ) -> ConversationResult:
        """Process the user input through the shared runner, streaming the answer."""
        ha_conversation_id = getattr(user_input, "conversation_id", None)
        try:
            await self._runner.async_run_streaming(chat_log, user_input)
        except Exception as e:
            error = ConversationError(
                message=f"Error processing conversation: {e}",
                code="CONVERSATION_PROCESSING_ERROR",
                details={"error": str(e), "conversation_id": ha_conversation_id},
            )
            _LOGGER.error(f"Error processing conversation: {error}")
            await self.async_handle_error(chat_log, error)

        return conversation.async_get_result_from_chat_log(user_input, chat_log)
