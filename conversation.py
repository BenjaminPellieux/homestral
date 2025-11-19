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
from mistralai import Mistral
from mistralai.models import UserMessage
from mistralai.models.toolexecutionentry import ToolExecutionEntry
from mistralai.models.messageoutputentry import MessageOutputEntry
from .const import *
import logging
import base64
import aiohttp
import os

_LOGGER = logging.getLogger(__name__)

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

    async def async_handle_error(self, chat_log, msg: str):
        chat_log.content.append(AssistantContent(
                agent_id=self._attr_unique_id,
                content=f"{msg}",
        ))

    async def _transcribe_audio(self, audio_data):
        """Transcribe audio data using Voxtral API."""
        try:
            # Encode audio data in base64
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')

            # Send audio to Voxtral API for STT
            response = await self._client.chat.complete(
                model="voxtral-mini-latest",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": audio_base64,
                        },
                        {
                            "type": "text",
                            "text": "Transcribe this audio.",
                        },
                    ]
                }],
            )
            return response.choices[0].message.content
        except Exception as e:
            _LOGGER.error(f"Error transcribing audio: {e}")
            return None

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log,
    ) -> ConversationResult:
        """Process the user input and call the API."""
        # Check if user_input contains audio data
        
        if user_input.attachments:
            # Transcribe audio using Voxtral API
            audio_data = await self._transcribe_audio(user_input.attachments[0].content)
            if audio_data:
                user_input.text = audio_data
            else:
                await self.async_handle_error(chat_log, "Error transcribing audio.")
                return conversation.async_get_result_from_chat_log(user_input, chat_log)
        


        _LOGGER.info(f"\n[DEBUG]: {self._conversation_id=}")
        if self._conversation_id is None:
            # Démarrer une nouvelle conversation
            try:
                response = self._client.beta.conversations.start(
                    agent_id=DEFAULT_AGENT_ID,
                    inputs=user_input.text,
                )
                self._conversation_id = response.conversation_id
                _LOGGER.info(f"\n[DEBUG]: {response=}")
            except Exception as e:
                _LOGGER.error(f"Error starting new conversation: {e}")
                await self.async_handle_error(chat_log, f"Error starting new conversation: {e}")
        else:
            # Continuer une conversation existante
            try:
                response = self._client.beta.conversations.append(
                    conversation_id=self._conversation_id,
                    inputs=user_input.text,
                )
                _LOGGER.info(f"\n[DEBUG]: {response=}")
            except Exception as e:
                _LOGGER.error(f"Error continuing conversation: {e}")
                self._conversation_id = None
                await self.async_handle_error(chat_log, f"Error continuing conversation: {e}")

        # Ajouter le contenu de l'assistant au chat_log
        
        _LOGGER.info(f" \n\n\n\n\n[DEBUG]: {type(response.outputs[0])=}")


        try:
            if isinstance(response.outputs[0], ToolExecutionEntry):
                content = response.outputs[1].content[0].text
            else:
                content = response.outputs[0].content 
        except Exception as e:
            _LOGGER.error(f"Error parsing response:  {e}")
            await self.async_handle_error(chat_log, f"Error parsing response: {e}")

        _LOGGER.info(f"\n[DEBUG]: {content=}")

        chat_log.content.append(AssistantContent(
            agent_id=self._attr_unique_id,
            content=content,
        ))
        
        return conversation.async_get_result_from_chat_log(user_input, chat_log)