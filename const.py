DOMAIN = "homestral"


# Constants for configuration
CONF_API_KEY = "api_key"
CONF_USE_AGENT = "use_agent"
CONF_AGENT_ID = "agent_id"
CONF_MODEL = "model"


# Default values
DEFAULT_NAME = "Homestral"
DEFAULT_CHAT_MODEL = "mistral-medium-latest"
DEFAULT_STT_MODEL = "voxtral-mini-latest"

# Home automation vocabulary for Voxtral 2 context_bias
# IMPORTANT: API requires single words only — pattern ^[^,\s]+$ (no spaces, no commas)
HOME_AUTOMATION_VOCAB = [
    "lumière", "prise", "thermostat", "volet", "store",
    "chauffage", "climatisation", "allume", "éteins",
    "brightness", "temperature", "lumières",
]

# TTS (Text-to-Speech) — Voxtral TTS
DEFAULT_TTS_MODEL  = "voxtral-mini-tts-2603"
DEFAULT_TTS_VOICE  = "casual_female"
DEFAULT_TTS_FORMAT = "mp3"

# Custom HA FunctionTool names
TOOL_GET_HA_STATE = "get_ha_state"
TOOL_LIST_HA_ENTITIES = "list_ha_entities"
TOOL_GET_HA_WEATHER = "get_ha_weather"

# Services
SERVICE_GENERATE_CONTENT = "generate_content"
SERVICE_CONTROL_DEVICE = "control_device"
