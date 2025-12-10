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
from mistralai.models.toolexecutionentry import ToolExecutionEntry
from mistralai.models.messageoutputentry import MessageOutputEntry
from mistralai.models import ConversationResponse
from .const import *
from .api_control import DeviceController
import logging
import base64
from .errors import ConversationError, APIError
from .logging_config import get_logger


_LOGGER = get_logger(__name__)

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
        self._device_controller = DeviceController(hass)

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
            error = AudioProcessingError(
                message=f"Error transcribing audio: {e}",
                code="AUDIO_TRANSCRIPTION_ERROR",
                details={"error": str(e), "audio_data_length": len(audio_data)}
            )
            _LOGGER.error(f"Error transcribing audio: {error}")
            return None

    async def _handle_device_control_command(self, command: str) -> str:
        """Handle device control commands from user input."""
        try:
            # Parse the command to extract device ID, action, and parameters
            # This is a simple parser - could be enhanced with NLP
            parts = command.lower().split()
            
            # Extract device ID (simple pattern matching)
            device_id = None
            action = None
            parameters = {}
            
            # Look for common device types
            for i, part in enumerate(parts):
                if part in ['light', 'switch', 'living', 'room', 'bedroom', 'kitchen']:
                    # Try to find the full entity ID
                    potential_id = f"{parts[i]}.{parts[i+1]}_{parts[i+2]}" if len(parts) > i+2 else parts[i]
                    # Check if this entity exists
                    try:
                        device_info = await self._device_controller.get_device_info(potential_id)
                        device_id = device_info['entity_id']
                        break
                    except:
                        continue
            
            if not device_id:
                return "I couldn't identify the device you're referring to. Please be more specific."
            
            # Extract action
            if 'turn on' in command.lower():
                action = 'turn_on'
            elif 'turn off' in command.lower():
                action = 'turn_off'
            elif 'open' in command.lower():
                action = 'open'
            elif 'close' in command.lower():
                action = 'close'
            elif 'set' in command.lower():
                action = 'set_temperature' if 'temperature' in command.lower() else 'set_brightness'
                # Extract parameters
                for part in parts:
                    if part.replace('.', '').isdigit():
                        parameters['temperature' if 'temperature' in command.lower() else 'brightness'] = float(part)
                        break
            
            if not action:
                return "I couldn't determine what action you want to perform."
            
            # Execute the command
            result = await self._device_controller.control_device(device_id, action, parameters)
            
            if result.get('success'):
                return f"Successfully {action.replace('_', ' ')} {device_id}"
            else:
                return f"Failed to {action.replace('_', ' ')} {device_id}"
                
        except Exception as e:
            error = ConversationError(
                message=f"Error handling device control command: {e}",
                code="DEVICE_CONTROL_COMMAND_ERROR",
                details={"command": command, "error": str(e)}
            )
            _LOGGER.error(f"Error handling device control command: {error}")
            return f"Sorry, I encountered an error while trying to control the device: {str(e)}"

    def start_conversation(self, user_input: ConversationInput) -> ConversationResponse:
        
        # Démarrer une nouvelle conversation
        if self._entry.data.get(CONF_USE_AGENT, False):
            # Use agent if specified in configuration
            _LOGGER.info("Starting new conversation with agent")
            return  self._client.beta.conversations.start(
                    agent_id=self._entry.data.get(CONF_AGENT_ID),
                    inputs=user_input.text,
            )
        else:
            # Use model if no agent specified
            _LOGGER.info("Starting new conversation with model")
            return  self._client.beta.conversations.start(
                model=self._entry.data.get(CONF_MODEL, DEFAULT_CHAT_MODEL),
                inputs=user_input.text
            )
        

    def keep_conversation(self, user_input: ConversationInput) -> ConversationResponse:
    
        _LOGGER.info("Continuing conversation with agent")
        return  self._client.beta.conversations.append(
                    conversation_id=self._conversation_id,
                    inputs=user_input.text,
                )



    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log,
    ) -> ConversationResult:
        """Process the user input and call the API."""
        _LOGGER.info(f"\n[DEBUG]: {self._conversation_id=}")
        try:
            # Check if this is a device control command
            user_text = user_input.text.lower()
            if any(keyword in user_text for keyword in ['turn on', 'turn off', 'open', 'close', 'set temperature', 'set brightness']):
                # Try to handle as device control command
                response_text = await self._handle_device_control_command(user_input.text)
                chat_log.content.append(AssistantContent(
                    agent_id=self._attr_unique_id,
                    content=response_text,
                ))
                return conversation.async_get_result_from_chat_log(user_input, chat_log)
            
            # Otherwise, handle as regular conversation
            if self._conversation_id is None:
                response = self.start_conversation(user_input)
            else:
                response = self.keep_conversation(user_input)
                # Continuer une conversation existante
                  
            # Parse the response
            self._conversation_id = response.conversation_id if hasattr(response, 'conversation_id') else None
            _LOGGER.info(f"\n[DEBUG]: {response=}")
            _LOGGER.info(f" \n\n\n\n\n[DEBUG]: {type(response.outputs[0])=}")
            try:
                if isinstance(response.outputs[0], ToolExecutionEntry):
                    content = response.outputs[1].content[0].text
                elif isinstance(response.outputs[0], MessageOutputEntry):
                    content = response.outputs[0].content
                else:
                    _LOGGER.error("Unknown response type")
                    await self.async_handle_error(chat_log, "Unknown response type")
                    return conversation.async_get_result_from_chat_log(user_input, chat_log)
            except Exception as e:
                error = ConversationError(
                    message=f"Error parsing response: {e}",
                    code="RESPONSE_PARSING_ERROR",
                    details={"error": str(e), "response": str(response) if 'response' in locals() else "No response"}
                )
                _LOGGER.error(f"Error parsing response: {error}")
                await self.async_handle_error(chat_log, error)
                return conversation.async_get_result_from_chat_log(user_input, chat_log)

            _LOGGER.info(f"\n[DEBUG]: {content=}")
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
