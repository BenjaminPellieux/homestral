from homeassistant.const import Platform

DOMAIN = "homestral"

PLATFORMS = [Platform.SENSOR, Platform.CONVERSATION, Platform.STT, Platform.TTS]

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

# Chat models. The aliases follow Mistral's newest non-deprecated release:
# - mistral-small-latest  -> Mistral Small 4, the model Mistral runs in its own voice
#                            pipeline (sub-second turns): default for voice.
# - mistral-large-latest  -> Mistral Large 4 (flagship, multimodal, 1M context).
# - mistral-medium-latest -> Mistral Medium 3.5 (agentic / coding).
DEFAULT_CHAT_MODEL = "mistral-small-latest"
AVAILABLE_CHAT_MODELS = [
    "mistral-small-latest",
    "mistral-large-latest",
    "mistral-medium-latest",
]
# Model ids stored by earlier releases that are no longer offered in the options form.
LEGACY_CHAT_MODEL_ALIASES = {
    "mistral-large-4": "mistral-large-latest",
}


def resolve_chat_model(model: str | None) -> str:
    """Map a stored chat model id onto a currently supported one."""
    if not model:
        return DEFAULT_CHAT_MODEL
    resolved = LEGACY_CHAT_MODEL_ALIASES.get(model, model)
    return resolved if resolved in AVAILABLE_CHAT_MODELS else DEFAULT_CHAT_MODEL


# STT — Voxtral 3 (https://docs.mistral.ai/studio/audio/migrate-from-voxtral-2)
STT_MODEL_BATCH_MINI = "voxtral-mini-transcribe-3-0"  # /v1/audio/transcriptions, 4B
STT_MODEL_BATCH_SMALL = "voxtral-small-transcribe-3-0"  # /v1/audio/transcriptions, higher accuracy
STT_MODEL_REALTIME = "voxtral-mini-transcribe-realtime-3-0"  # websocket, turn detection
STT_MODEL_CHAT_FALLBACK = "voxtral-small-latest"  # chat completions with input_audio (last resort)
DEFAULT_STT_MODEL = STT_MODEL_BATCH_MINI

# Home automation vocabulary sent as context_bias. Voxtral 3 accepts multi-word phrases;
# entries must not contain commas (one form field per entry on the wire).
HOME_AUTOMATION_VOCAB = [
    "lumière",
    "lumières",
    "prise",
    "thermostat",
    "volet roulant",
    "store",
    "chauffage",
    "climatisation",
    "allume",
    "éteins",
    "ouvre",
    "ferme",
    "température",
    "luminosité",
    "Home Assistant",
    "Homestral",
]

# TTS — Voxtral TTS 3 via /v1/audio/speech (24 kHz mono output)
DEFAULT_TTS_MODEL = "voxtral-mini-tts-3-0"
DEFAULT_TTS_FORMAT = "wav"
DEFAULT_TTS_LANGUAGE = "fr"
# Voxtral 3 preset voices (https://docs.mistral.ai/studio/audio/text-to-speech/voices).
# language -> [(voice_id, name)]; the first entry is the default voice for that language.
TTS_VOICES: dict[str, list[tuple[str, str]]] = {
    "fr": [("voice_592", "Marie"), ("voice_3137", "Manon"), ("voice_589", "Lea"), ("voice_3141", "Camille")],
    "en": [
        ("voice_478", "Sheila"),
        ("voice_447", "Margaret"),
        ("voice_485", "Rob"),
        ("voice_3150", "James"),
        ("voice_1787", "Mary"),
        ("voice_1786", "Sky"),
        ("voice_1788", "David"),
        ("voice_590", "Harriet"),
    ],
    "es": [("voice_483", "Elena")],
    "de": [("voice_481", "Heidi")],
    "it": [("voice_482", "Lorenzo")],
    "pt": [("voice_480", "Gabriela")],
    "nl": [("voice_3145", "Lotte")],
    "ar": [("voice_479", "Maryam")],
    "hi": [("voice_3139", "Ananya"), ("voice_3153", "Himanshu")],
}

# Custom HA FunctionTool names
TOOL_GET_HA_STATE = "get_ha_state"
TOOL_LIST_HA_ENTITIES = "list_ha_entities"
TOOL_GET_HA_WEATHER = "get_ha_weather"

# Services
SERVICE_CONTROL_DEVICE = "control_device"
