from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationResult,
    ConversationInput,
    AbstractConversationAgent,
)


from markdown import markdown
from homeassistant.components.conversation.chat_log import AssistantContent

import homeassistant.components.conversation as conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.const import MATCH_ALL
from mistralai import Mistral
from mistralai.models import UserMessage
from .const import *
import logging

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

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log,
    ) -> ConversationResult:
        """Process the user input and call the API."""
        _LOGGER.info(f"\n[DEBUG]\t handle message: {user_input.text=}")
        try:
            response = self._client.chat.complete(
                model=DEFAULT_CHAT_MODEL,
                messages=[UserMessage(content=user_input.text)],
            )
            _LOGGER.info(f"\n[DEBUG]\t handle message: {response=} {type(response.choices[0].message.content)=}")
             # Créer un objet AssistantContent avec le contenu de la réponse
            # html_content = markdown(response.choices[0].message.content)
            assistant_content = AssistantContent(
                agent_id=self._attr_unique_id, # pyright: ignore[reportArgumentType]
                content=response.choices[0].message.content,
                # content=html_content
            )
            # Utiliser async_add_assistant_content_without_tools si la réponse ne contient pas d'appels d'outils
            #chat_log.async_add_assistant_content_without_tools() 
            chat_log.content.append(assistant_content)
        except Exception as e:
            _LOGGER.info(f"\n[DEBUG]\t ERROR {e=}")
            _LOGGER.error(f"Error processing conversation: {e}")
            assistant_content = AssistantContent(
                agent_id=self._attr_unique_id, # pyright: ignore[reportArgumentType]
                content=f"Error processing conversation: {e}",
            )
            # Utiliser async_add_assistant_content_without_tools si la réponse ne contient pas d'appels d'outils
            #chat_log.async_add_assistant_content_without_tools() 
            chat_log.content.append(assistant_content)

        return conversation.async_get_result_from_chat_log(user_input, chat_log)
