from homeassistant.const import Platform

DOMAIN = "homestral"

PLATFORMS = [Platform.SENSOR, Platform.CONVERSATION, Platform.STT, Platform.TTS]

# Constants for configuration
CONF_API_KEY = "api_key"
CONF_USE_AGENT = "use_agent"
CONF_AGENT_ID = "agent_id"
CONF_MODEL = "model"
CONF_MAX_TOOL_ITERATIONS = "max_tool_iterations"
# Home Assistant LLM APIs exposed to the model (llm.async_get_apis); "assist" exposes the
# Assist intents, which respect the per-entity "exposed to Assist" setting and the area of
# the satellite that is speaking.
CONF_LLM_HASS_API = "llm_hass_api"
DEFAULT_LLM_HASS_API = ["assist"]
# HomeStral's own tools (control_ha_device, get_ha_state, list_ha_entities). They bypass the
# exposure settings, so they are off for new installs and kept on for migrated entries.
CONF_LEGACY_TOOLS = "legacy_tools"
DEFAULT_LEGACY_TOOLS = False
# Extra system prompt replacing the built-in one when set.
CONF_PROMPT = "prompt"
DEFAULT_PROMPT = ""
# Ask for a spoken confirmation before unlocking, disarming or opening up the house.
CONF_CONFIRM_SENSITIVE = "confirm_sensitive_actions"
DEFAULT_CONFIRM_SENSITIVE = False
# Tool names and entity domains treated as sensitive when the option is on.
SENSITIVE_TOOL_NAMES = frozenset({"HassTurnOn", "HassTurnOff", "control_ha_device"})
SENSITIVE_DOMAINS = frozenset({"lock", "alarm_control_panel", "cover"})


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
# Language tags Home Assistant may use that Mistral spells differently. Mistral only takes
# two-letter ISO 639-1 codes: "fil" is rejected with a 422, and Norwegian is "no" only.
LANGUAGE_ALIASES = {"nb": "no", "fil": "tl"}
# Realtime transcription rejects any language outside this list. Taken from the list the
# realtime API returns for an unsupported code (probed 2026-10-26); the docs say "45".
STT_REALTIME_LANGUAGES = [
    "ar",
    "bg",
    "bn",
    "ca",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "eu",
    "fa",
    "fi",
    "fr",
    "ga",
    "gu",
    "hi",
    "hr",
    "hu",
    "id",
    "is",
    "it",
    "ja",
    "km",
    "kn",
    "ko",
    "lb",
    "lt",
    "lv",
    "mk",
    "ml",
    "mr",
    "ms",
    "mt",
    "my",
    "nl",
    "no",
    "or",
    "pa",
    "pl",
    "ps",
    "pt",
    "ro",
    "ru",
    "sk",
    "sl",
    "sr",
    "sv",
    "ta",
    "te",
    "th",
    "tl",
    "tr",
    "uk",
    "ur",
    "vi",
    "zh",
]
# File transcription accepts any ISO 639-1 code without complaint, so the API gives no list.
# These are the languages Mistral benchmarks it on (FLEURS, Voxtral 3 announcement); the
# docs say "50". Codes outside STT_REALTIME_LANGUAGES go straight to file transcription.
STT_BATCH_LANGUAGES = [
    "ar",
    "bg",
    "bn",
    "ca",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "fa",
    "fi",
    "fr",
    "gu",
    "hi",
    "hu",
    "id",
    "is",
    "it",
    "ja",
    "kn",
    "ko",
    "lt",
    "lv",
    "mk",
    "ml",
    "mr",
    "ms",
    "nl",
    "no",
    "pl",
    "pt",
    "ro",
    "ru",
    "sk",
    "sl",
    "sv",
    "te",
    "th",
    "tl",
    "tr",
    "uk",
    "vi",
    "zh",
]
# Languages accepted by the STT entity: either mode, plus the aliases Home Assistant may use.
_STT_LANGUAGES = {*STT_REALTIME_LANGUAGES, *STT_BATCH_LANGUAGES}
STT_SUPPORTED_LANGUAGES = sorted(
    _STT_LANGUAGES | {alias for alias, code in LANGUAGE_ALIASES.items() if code in _STT_LANGUAGES}
)
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
# Streaming path: ask for "wav" rather than "pcm". Measured against the live API on
# 2026-10-24: `pcm` returns 32-bit FLOAT samples (f32le, 24 kHz mono), which played as
# 16-bit integers is full-scale noise, and nothing in the API or the SDK declares the
# encoding. `wav` streams a RIFF header with an unknown length (0xFFFFFFFF) followed by
# 16-bit PCM, so the stream describes itself and we never have to guess again.
TTS_STREAM_FORMAT = "wav"
# Fallback parameters, used only if a streamed container has no readable header.
TTS_SAMPLE_RATE = 24000
TTS_SAMPLE_WIDTH = 2
TTS_CHANNELS = 1
# Voxtral 3 preset voices (https://docs.mistral.ai/studio/audio/text-to-speech/voices), checked
# against GET /v1/audio/voices on 2026-10-26. The speech API takes no language: the voice sets
# it, so these keys are the TTS languages. The other TTS languages need a cloned voice.
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
        ("voice_591", "Fred"),
        ("voice_3149", "Hugo"),
        ("voice_3147", "Howard"),
    ],
    "es": [("voice_483", "Elena")],
    "de": [("voice_481", "Heidi")],
    "it": [("voice_482", "Lorenzo")],
    "pt": [("voice_480", "Gabriela")],
    "nl": [("voice_3145", "Lotte")],
    "ar": [("voice_479", "Maryam")],
    "hi": [("voice_3139", "Ananya"), ("voice_3153", "Himanshu")],
    "ca": [("voice_3143", "Jordi")],
    "hu": [("voice_3146", "Olivia")],
    "ja": [("voice_3133", "Haruto")],
    "ko": [("voice_3136", "Sung"), ("voice_3135", "Jin")],
    "no": [("voice_3134", "Lars")],
    "pl": [("voice_3154", "Leon")],
    "ro": [("voice_3155", "Irina")],
    "ru": [("voice_3132", "Tatiana")],
    "tr": [("voice_3138", "Oran")],
    "uk": [("voice_3140", "Taras")],
    "vi": [("voice_3144", "Huong")],
    "zh": [("voice_3142", "Mei")],
}
# Languages accepted by the TTS entity: the voice languages plus the aliases Home Assistant may use.
TTS_SUPPORTED_LANGUAGES = sorted(
    {*TTS_VOICES} | {alias for alias, code in LANGUAGE_ALIASES.items() if code in TTS_VOICES}
)

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
# Pronunciation hints, one "word=ipa" per line, sent as phoneme_hints.
CONF_TTS_PRONUNCIATIONS = "tts_pronunciations"
DEFAULT_TTS_PRONUNCIATIONS = ""
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
# Home Assistant's own LLM API can read calendars but not write to them, so this tool
# fills the gap and stays available even when the legacy tools are off.
TOOL_CREATE_CALENDAR_EVENT = "create_calendar_event"
# CalendarEntityFeature.CREATE_EVENT; an entity without it rejects calendar.create_event.
CALENDAR_FEATURE_CREATE_EVENT = 1

# Services
SERVICE_CONTROL_DEVICE = "control_device"
