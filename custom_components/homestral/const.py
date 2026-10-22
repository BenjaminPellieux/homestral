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
# Languages accepted by the STT entity (ISO 639-1); all are in the Voxtral 3 batch and realtime sets.
STT_SUPPORTED_LANGUAGES = ["en", "fr", "zh", "hi", "es", "ar", "pt", "ru", "de", "ja", "ko", "it", "nl"]
# Home Assistant hands STT entities PCM 16-bit mono at 16 kHz; this is also the realtime default.
STT_SAMPLE_RATE = 16000

# STT options
CONF_STT_MODE = "stt_mode"
STT_MODE_REALTIME = "realtime"
STT_MODE_BATCH = "batch"
STT_MODES = [STT_MODE_REALTIME, STT_MODE_BATCH]
DEFAULT_STT_MODE = STT_MODE_REALTIME

CONF_STT_BATCH_MODEL = "stt_batch_model"
STT_BATCH_MODELS = {"mini": STT_MODEL_BATCH_MINI, "small": STT_MODEL_BATCH_SMALL}
DEFAULT_STT_BATCH_MODEL = "mini"

# target_streaming_delay_ms: the API accepts 80 to 1200 ms or 2400 ms; 480 is the recommended start.
CONF_STT_STREAMING_DELAY_MS = "stt_streaming_delay_ms"
STT_STREAMING_DELAY_CHOICES = [240, 480, 960]
DEFAULT_STT_STREAMING_DELAY_MS = 480

CONF_STT_TURN_DETECTION = "stt_turn_detection"
STT_TURN_DETECTION_OFF = "off"
STT_TURN_DETECTION_DEFAULT = "default"
STT_TURN_DETECTION_AGGRESSIVE = "aggressive"
STT_TURN_DETECTION_CHOICES = [STT_TURN_DETECTION_OFF, STT_TURN_DETECTION_DEFAULT, STT_TURN_DETECTION_AGGRESSIVE]
DEFAULT_STT_TURN_DETECTION = STT_TURN_DETECTION_DEFAULT

CONF_STT_LANGUAGE = "stt_language"
STT_LANGUAGE_PIPELINE = "pipeline"  # send the pipeline language as ISO 639-1
STT_LANGUAGE_AUTO = "auto"  # let Voxtral detect it
STT_LANGUAGE_CHOICES = [STT_LANGUAGE_PIPELINE, STT_LANGUAGE_AUTO]
DEFAULT_STT_LANGUAGE = STT_LANGUAGE_PIPELINE

CONF_STT_CUSTOM_VOCABULARY = "stt_custom_vocabulary"  # one phrase per line or comma-separated
DEFAULT_STT_CUSTOM_VOCABULARY = ""
CONF_STT_BIAS_ENTITIES = "stt_bias_entities"  # add exposed entity, area and floor names to context_bias
DEFAULT_STT_BIAS_ENTITIES = True
CONF_STT_CHAT_FALLBACK = "stt_chat_fallback"  # last-resort chat completion with audio input
DEFAULT_STT_CHAT_FALLBACK = False

# context_bias entries share the context window with the audio: keep the list short.
STT_VOCABULARY_MAX_ENTRIES = 150
STT_VOCABULARY_CACHE_SECONDS = 60
# PCM kept aside during a realtime session so the batch fallback can reuse it (60 s at 16 kHz).
STT_REALTIME_BUFFER_MAX_BYTES = STT_SAMPLE_RATE * 2 * 60

# Fired on turn.eager_end (the user has probably finished speaking): a hook for pre-warming.
EVENT_STT_EAGER_END = "homestral_stt_eager_end"

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
DEFAULT_TTS_FORMAT = "wav"  # non-streaming path: one request, cacheable by Home Assistant
DEFAULT_TTS_LANGUAGE = "fr"
# Streaming path: pcm chunks (time to first audio ~0.8 s against ~3 s for mp3) wrapped in a
# streaming WAV header. Voxtral TTS 3 always returns 24 kHz, 16-bit, mono.
TTS_STREAM_FORMAT = "pcm"
TTS_SAMPLE_RATE = 24000
TTS_SAMPLE_WIDTH = 2
TTS_CHANNELS = 1
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

# Inline delivery tags (https://docs.mistral.ai/studio/audio/text-to-speech/emotion-tags).
# Written as [emotion=<value>] / [pace=<value>] at the start of the text they apply to.
# Tested in English, expected but untested in fr/de/es/it/pt/hi.
TTS_EMOTIONS = [
    "amused",
    "angry",
    "anxious",
    "apologetic",
    "appreciative",
    "assertive",
    "bored",
    "calm",
    "confident",
    "confused",
    "critical",
    "curious",
    "determined",
    "disappointed",
    "disgusted",
    "excited",
    "frustrated",
    "grateful",
    "happy",
    "hopeful",
    "playful",
    "proud",
    "reflective",
    "resigned",
    "sad",
    "sarcastic",
    "skeptical",
    "somber",
    "surprised",
    "tense",
    "tired",
    "urgent",
    "warm",
    "wistful",
]
TTS_PACES = ["very-slow", "slow", "moderate", "fast", "very-fast"]
TTS_NONE = "none"  # "no default emotion / pace" choice in the options form

# TTS options
CONF_TTS_VOICE = "tts_voice"  # per-entry default voice id ("" = first preset of the language)
DEFAULT_TTS_VOICE = ""
CONF_TTS_EXPRESSIVENESS = "tts_expressiveness"  # 1.0 to 5.0; 0 means "let the service decide"
DEFAULT_TTS_EXPRESSIVENESS = 0.0
MIN_TTS_EXPRESSIVENESS = 1.0
MAX_TTS_EXPRESSIVENESS = 5.0
CONF_TTS_DEFAULT_EMOTION = "tts_default_emotion"
DEFAULT_TTS_EMOTION = TTS_NONE
CONF_TTS_DEFAULT_PACE = "tts_default_pace"
DEFAULT_TTS_PACE = TTS_NONE
# Per-request options accepted from tts.speak / the Assist pipeline
TTS_OPTION_EMOTION = "emotion"
TTS_OPTION_PACE = "pace"
# Sentence batching while the conversation answer is still streaming: synthesize the first
# sentence immediately, then up to 3, then everything available (same schedule as HA core's
# ElevenLabs integration).
TTS_SENTENCE_SCHEDULE = [1, 3]

# Custom HA FunctionTool names
TOOL_GET_HA_STATE = "get_ha_state"
TOOL_LIST_HA_ENTITIES = "list_ha_entities"
TOOL_GET_HA_WEATHER = "get_ha_weather"

# Services
SERVICE_CONTROL_DEVICE = "control_device"
