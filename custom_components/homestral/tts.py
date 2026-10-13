import asyncio

from homeassistant.components import tts
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DEFAULT_TTS_FORMAT, DEFAULT_TTS_MODEL
from .logging_config import get_logger

_LOGGER = get_logger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Voxtral TTS entity."""
    async_add_entities([VoxtralTtsProvider(hass, config_entry)])


class VoxtralTtsProvider(tts.TextToSpeechEntity):
    """Voxtral text-to-speech provider using Mistral audio.speech API."""

    _attr_supported_languages = ["en", "fr", "es", "de", "pt", "it", "nl", "hi", "ar"]
    _attr_default_language = "fr"
    # voice_id omitted until valid preset IDs are confirmed — API uses its default

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass = hass
        self._attr_name = "Voxtral TTS"
        self._attr_unique_id = f"{config_entry.entry_id}-tts"
        self._client = config_entry.runtime_data

    async def async_get_tts_audio(
        self,
        message: str,
        language: str,
        options: dict | None = None,
    ) -> tts.TtsAudioType:
        """Convert text to speech using Voxtral TTS."""
        _LOGGER.info(f"[TTS] synthesising {len(message)} chars, lang={language}")

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.audio.speech.complete(
                    input=message,
                    model=DEFAULT_TTS_MODEL,
                    response_format=DEFAULT_TTS_FORMAT,
                    # voice_id omitted — preset IDs TBD; API uses default voice
                ),
            )
            audio = response.audio_data
            _LOGGER.info(f"[TTS] received {len(audio)} bytes")
            return DEFAULT_TTS_FORMAT, audio

        except Exception as exc:
            _LOGGER.error(f"[TTS] error synthesising speech: {exc}")
            return None, None
