from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

DOMAIN = "homestral"

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required('api_key'): cv.string,
    })
}, extra=vol.ALLOW_EXTRA)

def setup(hass, config):
    """Your controller/hub setup code."""
    api_key = config[DOMAIN]['api_key']
    client = MistralClient(api_key=api_key)

    def handle_chat(call):
        message = call.data.get('message')
        chat_response = client.chat(
            messages=[ChatMessage(role="user", content=message)]
        )
        return chat_response.choices[0].message.content

    def handle_speech(call):
        text = call.data.get('text')
        speech_response = client.text_to_speech(text)
        return speech_response.content

    hass.services.register(DOMAIN, 'send_message', handle_chat)
    hass.services.register(DOMAIN, 'speak', handle_speech)

    return True

