"""Voxtral TTS 3 text-to-speech entity (Mistral /v1/audio/speech).

Two paths:

* ``async_stream_tts_audio`` — the Assist pipeline streams the conversation answer
  into the entity. The text is split into sentences, each batch is synthesized with
  ``stream=True`` (SSE ``speech.audio.delta`` chunks of raw PCM) and the audio is
  returned as one streaming WAV: a header with ``nframes=0`` followed by the PCM,
  so playback starts before the model has finished writing.
* ``async_get_tts_audio`` — one-shot synthesis (``tts.speak``, cached phrases):
  a single request with ``response_format="wav"``.

Both share voice resolution and the inline delivery tags (``[emotion=...]``,
``[pace=...]``) prefixed to the text.
"""

from __future__ import annotations

import asyncio
import base64
import io
import wave
from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.components import tts
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from sentence_stream import SentenceBoundaryDetector

from .const import (
    CONF_TTS_DEFAULT_EMOTION,
    CONF_TTS_DEFAULT_PACE,
    CONF_TTS_EXPRESSIVENESS,
    CONF_TTS_VOICE,
    DEFAULT_TTS_EMOTION,
    DEFAULT_TTS_EXPRESSIVENESS,
    DEFAULT_TTS_FORMAT,
    DEFAULT_TTS_LANGUAGE,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_PACE,
    DEFAULT_TTS_VOICE,
    MAX_TTS_EXPRESSIVENESS,
    MIN_TTS_EXPRESSIVENESS,
    TTS_CHANNELS,
    TTS_EMOTIONS,
    TTS_NONE,
    TTS_OPTION_EMOTION,
    TTS_OPTION_PACE,
    TTS_PACES,
    TTS_SAMPLE_RATE,
    TTS_SAMPLE_WIDTH,
    TTS_SENTENCE_SCHEDULE,
    TTS_STREAM_FORMAT,
    TTS_VOICES,
)
from .helpers import get_option
from .logging_config import get_logger

_LOGGER = get_logger(__name__)


def language_key(language: str | None) -> str | None:
    """Map an HA language tag (``fr-FR``, ``en_GB``) to a TTS_VOICES key, or None if unsupported."""
    if not language:
        return None
    key = language.replace("_", "-").split("-")[0].lower()
    return key if key in TTS_VOICES else None


def decode_audio(audio_data: str | bytes | bytearray) -> bytes:
    """The speech API returns the audio as a base64 string (``SpeechResponse.audio_data``)."""
    if isinstance(audio_data, bytes | bytearray):
        return bytes(audio_data)
    return base64.b64decode(audio_data)


def delivery_tags(emotion: str | None, pace: str | None) -> str:
    """Build the inline tag prefix, dropping values outside the documented lists."""
    prefix = ""
    if emotion and emotion != TTS_NONE:
        if emotion in TTS_EMOTIONS:
            prefix += f"[emotion={emotion}]"
        else:
            _LOGGER.warning(f"[TTS] unknown emotion {emotion!r}, ignored")
    if pace and pace != TTS_NONE:
        if pace in TTS_PACES:
            prefix += f"[pace={pace}]"
        else:
            _LOGGER.warning(f"[TTS] unknown pace {pace!r}, ignored")
    return prefix


def streaming_wav_header() -> bytes:
    """A WAV header with nframes=0: tells the player the length is unknown (Wyoming pattern)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(TTS_CHANNELS)
        wav.setsampwidth(TTS_SAMPLE_WIDTH)
        wav.setframerate(TTS_SAMPLE_RATE)
    return buf.getvalue()


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
    _attr_supported_options = [tts.ATTR_VOICE, TTS_OPTION_EMOTION, TTS_OPTION_PACE]

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = config_entry
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

    # ------------------------------------------------------------------
    # Request shaping
    # ------------------------------------------------------------------

    def resolve_voice(self, language: str | None, options: dict[str, Any] | None) -> str:
        """Per-request voice, else the configured default, else the first preset of the language."""
        if options and options.get(tts.ATTR_VOICE):
            return str(options[tts.ATTR_VOICE])
        configured = str(get_option(self._entry, CONF_TTS_VOICE, DEFAULT_TTS_VOICE) or "").strip()
        if configured:
            return configured
        return TTS_VOICES[language_key(language) or DEFAULT_TTS_LANGUAGE][0][0]

    def resolve_tags(self, options: dict[str, Any] | None) -> str:
        """Per-request emotion and pace, falling back to the configured defaults."""
        options = options or {}
        emotion = options.get(TTS_OPTION_EMOTION) or get_option(
            self._entry, CONF_TTS_DEFAULT_EMOTION, DEFAULT_TTS_EMOTION
        )
        pace = options.get(TTS_OPTION_PACE) or get_option(self._entry, CONF_TTS_DEFAULT_PACE, DEFAULT_TTS_PACE)
        return delivery_tags(emotion, pace)

    def _speech_kwargs(self, voice: str) -> dict[str, Any]:
        """Model, voice and expressiveness shared by both paths."""
        kwargs: dict[str, Any] = {"model": DEFAULT_TTS_MODEL, "voice_id": voice}
        expressiveness = float(get_option(self._entry, CONF_TTS_EXPRESSIVENESS, DEFAULT_TTS_EXPRESSIVENESS) or 0)
        if MIN_TTS_EXPRESSIVENESS <= expressiveness <= MAX_TTS_EXPRESSIVENESS:
            kwargs["expressiveness"] = expressiveness
        return kwargs

    # ------------------------------------------------------------------
    # Streaming path (Assist pipeline)
    # ------------------------------------------------------------------

    async def async_stream_tts_audio(self, request: tts.TTSAudioRequest) -> tts.TTSAudioResponse:
        """Synthesize the answer sentence by sentence while it is still being written."""
        voice = self.resolve_voice(request.language, request.options)
        tags = self.resolve_tags(request.options)
        kwargs = self._speech_kwargs(voice)
        _LOGGER.info(f"[TTS stream] lang={request.language} voice={voice} tags={tags or 'none'}")
        return tts.TTSAudioResponse(DEFAULT_TTS_FORMAT, self._stream_audio(request, kwargs, tags))

    async def _stream_audio(
        self, request: tts.TTSAudioRequest, kwargs: dict[str, Any], tags: str
    ) -> AsyncGenerator[bytes]:
        """Yield a streaming WAV header then the PCM of each synthesized batch."""
        header_sent = False
        first_batch = True
        try:
            async for text in self._sentence_batches(request.message_gen):
                # Delivery tags apply from their position to the end of the input: the first
                # batch carries them so the whole answer is spoken in that style.
                payload = f"{tags}{text}" if first_batch else text
                first_batch = False
                async for chunk in self._synthesize_pcm(payload, kwargs):
                    if not header_sent:
                        header_sent = True
                        yield streaming_wav_header()
                    yield chunk
        except Exception as exc:
            if not header_sent:
                _LOGGER.error(f"[TTS stream] synthesis failed before any audio: {exc}")
                raise HomeAssistantError(f"Voxtral TTS failed: {exc}") from exc
            # Audio is already playing: stop here rather than cutting the player off with an error.
            _LOGGER.error(f"[TTS stream] synthesis interrupted, answer truncated: {exc}")
            return
        if not header_sent:
            _LOGGER.warning("[TTS stream] no audio returned")
            yield streaming_wav_header()

    @staticmethod
    async def _sentence_batches(message_gen: AsyncGenerator[str]) -> AsyncGenerator[str]:
        """Group the incoming text into sentence batches (1, then 3, then everything available).

        The text arrives in arbitrary chunks that do not respect sentence boundaries, so the
        boundary detector reassembles them; the schedule keeps the first spoken words early
        while later batches get longer (fewer requests, better prosody).
        """
        detector = SentenceBoundaryDetector()
        schedule = list(TTS_SENTENCE_SCHEDULE)
        pending: list[str] = []

        def take(count: int | None) -> str:
            batch = pending[:count] if count is not None else pending[:]
            del pending[: len(batch)]
            return " ".join(part.strip() for part in batch if part.strip()).strip()

        async for text_chunk in message_gen:
            for sentence in detector.add_chunk(text_chunk):
                if sentence.strip():
                    pending.append(sentence)
            while pending:
                wanted = schedule[0] if schedule else None
                if wanted is not None and len(pending) < wanted:
                    break
                if schedule:
                    schedule.pop(0)
                if batch := take(wanted):
                    yield batch
        if tail := detector.finish():
            pending.append(tail)
        if batch := take(None):
            yield batch

    async def _synthesize_pcm(self, text: str, kwargs: dict[str, Any]) -> AsyncGenerator[bytes]:
        """Stream one batch as raw PCM chunks."""
        _LOGGER.debug(f"[TTS stream] synthesising {len(text)} chars")
        stream = await self._client.audio.speech.complete_async(
            input=text, response_format=TTS_STREAM_FORMAT, stream=True, **kwargs
        )
        async with stream as events:
            async for event in events:
                name = getattr(event, "event", None) or getattr(getattr(event, "data", None), "type", None)
                if name == "speech.audio.delta":
                    yield decode_audio(event.data.audio_data)
                elif name == "speech.audio.done":
                    _LOGGER.debug(f"[TTS stream] batch done, usage={getattr(event.data, 'usage', '?')}")
                    return

    # ------------------------------------------------------------------
    # One-shot path (tts.speak, cached phrases)
    # ------------------------------------------------------------------

    async def async_get_tts_audio(
        self,
        message: str,
        language: str,
        options: dict[str, Any] | None = None,
    ) -> tts.TtsAudioType:
        """Convert text to speech in a single request."""
        voice = self.resolve_voice(language, options)
        payload = f"{self.resolve_tags(options)}{message}"
        _LOGGER.info(f"[TTS] synthesising {len(payload)} chars, lang={language}, voice={voice}")

        try:
            response = await self._client.audio.speech.complete_async(
                input=payload,
                response_format=DEFAULT_TTS_FORMAT,
                **self._speech_kwargs(voice),
            )
            audio = decode_audio(response.audio_data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.error(f"[TTS] error synthesising speech: {exc}")
            return None, None

        _LOGGER.info(f"[TTS] received {len(audio)} bytes")
        return DEFAULT_TTS_FORMAT, audio
