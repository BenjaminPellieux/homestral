DOMAIN = "homestral"


# Constants for configuration
CONF_API_KEY = "api_key"
CONF_USE_AGENT = "use_agent"
CONF_AGENT_ID = "agent_id"
CONF_MODEL = "model"
CONF_MAX_TOOL_ITERATIONS = "max_tool_iterations"


# Default values
DEFAULT_NAME = "Homestral"
# Tool loop — max number of tool-call iterations per conversation turn
DEFAULT_MAX_TOOL_ITERATIONS = 5
MIN_TOOL_ITERATIONS = 1
MAX_TOOL_ITERATIONS = 10
# Chat model — `mistral-large-latest` tracks Mistral's newest Large release, currently
# Mistral Large 4 (v26.10, "Le Chonk"), the flagship open-weight multimodal MoE model
# (1M context). `mistral-large-4` is the pinned preview ID.
DEFAULT_CHAT_MODEL = "mistral-large-latest"
# Selectable chat models in the config flow (aliases follow the newest non-deprecated release)
AVAILABLE_CHAT_MODELS = [
    "mistral-large-latest",   # Mistral Large 4 (flagship, multimodal, 1M ctx)
    "mistral-large-4",        # Mistral Large 4 — pinned preview ID
    "mistral-medium-latest",  # Mistral Medium 3.5 (agentic / coding)
    "mistral-small-latest",   # Mistral Small 4 (efficient hybrid)
]
# STT — Voxtral Mini Transcribe 2 (Voxtral 2) via /v1/audio/transcriptions
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
