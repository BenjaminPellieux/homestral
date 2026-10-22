"""Voxtral TTS 3 text-to-speech entity (Mistral /v1/audio/speech)."""

from __future__ import annotations

import base64
from typing import Any

from homeassistant.components import tts
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DEFAULT_TTS_FORMAT, DEFAULT_TTS_LANGUAGE, DEFAULT_TTS_MODEL, TTS_VOICES
from .logging_config import get_logger

_LOGGER = get_logger(__name__)


def language_key(language: str | None) -> str | None:
    """Map an HA language tag (``fr-FR``, ``en_GB``) to a TTS_VOICES key, or None if unsupported."""
    if not language:
        return None
    key = language.replace("_", "-").split("-")[0].lower()
    return key if key in TTS_VOICES else None


def resolve_voice(language: str | None, options: dict[str, Any] | None) -> str:
    """Return the voice id to send: the option/pipeline voice, else the language default."""
    if options and options.get(tts.ATTR_VOICE):
        return str(options[tts.ATTR_VOICE])
    return TTS_VOICES[language_key(language) or DEFAULT_TTS_LANGUAGE][0][0]


def decode_audio(audio_data: str | bytes | bytearray) -> bytes:
    """The speech API returns the audio as a base64 string (``SpeechResponse.audio_data``)."""
    if isinstance(audio_data, (bytes, bytearray)):
        return bytes(audio_data)
    return base64.b64decode(audio_data)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Voxtral TTS entity."""
    async_add_entities([VoxtralTtsProvider(hass, config_entry)])


class VoxtralTtsProvider(tts.TextToSpeechEntity):
    """Voxtral TTS 3 provider using the Mistral audio.speech API."""

    _attr_supported_languages = list(TTS_VOICES)
    _attr_default_language = DEFAULT_TTS_LANGUAGE
    _attr_supported_options = [tts.ATTR_VOICE]

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass = hass
        self._attr_name = "Voxtral TTS"
        self._attr_unique_id = f"{config_entry.entry_id}-tts"
        self._client = config_entry.runtime_data.client

    @callback
    def async_get_supported_voices(self, language: str) -> list[tts.Voice] | None:
        """Return the Voxtral 3 preset voices for a language."""
        key = language_key(language)
        if key is None:
            return None
        return [tts.Voice(voice_id, name) for voice_id, name in TTS_VOICES[key]]

    async def async_get_tts_audio(
        self,
        message: str,
        language: str,
        options: dict[str, Any] | None = None,
    ) -> tts.TtsAudioType:
        """Convert text to speech using Voxtral TTS 3."""
        voice = resolve_voice(language, options)
        _LOGGER.info(f"[TTS] synthesising {len(message)} chars, lang={language}, voice={voice}")

        try:
            response = await self._client.audio.speech.complete_async(
                model=DEFAULT_TTS_MODEL,
                input=message,
                voice_id=voice,
                response_format=DEFAULT_TTS_FORMAT,
            )
            audio = decode_audio(response.audio_data)
        except Exception as exc:
            _LOGGER.error(f"[TTS] error synthesising speech: {exc}")
            return None, None

        _LOGGER.info(f"[TTS] received {len(audio)} bytes")
        return DEFAULT_TTS_FORMAT, audio
