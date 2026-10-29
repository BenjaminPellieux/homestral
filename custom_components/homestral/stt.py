"""Voxtral 3 speech-to-text entity: realtime websocket with turn detection, batch fallback."""

from __future__ import annotations

import asyncio
import base64
import io
import math
import wave
from array import array
from collections.abc import AsyncIterable
from contextlib import suppress
from dataclasses import dataclass

from homeassistant.components import stt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from mistralai.client.models import (
    File as MistralFile,
)
from mistralai.client.models import (
    RealtimeTranscriptionError,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
    TurnDetectionEagerEndEvent,
    TurnDetectionEndEvent,
)

from .const import (
    CONF_API_KEY,
    CONF_STT_BATCH_MODEL,
    CONF_STT_CHAT_FALLBACK,
    CONF_STT_LANGUAGE,
    CONF_STT_MODE,
    CONF_STT_STREAMING_DELAY_MS,
    CONF_STT_TURN_DETECTION,
    DEFAULT_STT_BATCH_MODEL,
    DEFAULT_STT_CHAT_FALLBACK,
    DEFAULT_STT_LANGUAGE,
    DEFAULT_STT_MODE,
    DEFAULT_STT_STREAMING_DELAY_MS,
    DEFAULT_STT_TURN_DETECTION,
    EVENT_STT_EAGER_END,
    STT_BATCH_MODELS,
    STT_LANGUAGE_AUTO,
    STT_MODE_BATCH,
    STT_MODE_REALTIME,
    STT_MODEL_BATCH_MINI,
    STT_MODEL_CHAT_FALLBACK,
    STT_MODEL_REALTIME,
    STT_REALTIME_BUFFER_MAX_BYTES,
    STT_REALTIME_LANGUAGES,
    STT_SAMPLE_RATE,
    STT_SUPPORTED_LANGUAGES,
)
from .context_builder import async_stt_vocabulary
from .helpers import get_option, mistral_language
from .logging_config import get_logger
from .voxtral_realtime import RealtimeSession, RealtimeSessionError, turn_detection_preset

_LOGGER = get_logger(__name__)

# Safety nets: a whole realtime utterance, the wait for transcription.done after
# input_audio.end, and one batch request.
REALTIME_TOTAL_TIMEOUT = 60.0
REALTIME_DONE_TIMEOUT = 10.0
BATCH_TIMEOUT = 30.0


def normalize_language(language: str | None, mode: str) -> str | None:
    """Pipeline language (``fr-FR``, ``en_GB``) to ISO 639-1, or None to let Voxtral detect it."""
    if mode == STT_LANGUAGE_AUTO:
        return None
    return mistral_language(language)


def describe_level(pcm: bytes, sample_rate: int = STT_SAMPLE_RATE) -> str:
    """Summarise an utterance's duration and level, to tell a bad mic from a bad model.

    Speech should sit near -20 dBFS RMS. Much hotter means the input is clipping, much
    quieter means the model is being asked to transcribe near the noise floor; both show
    up as "the speech recognition is unreliable".
    """
    samples = len(pcm) // 2
    if not samples:
        return "no audio"
    values = array("h")
    values.frombytes(pcm[: samples * 2])
    peak = max(max(values), -min(values))
    rms = math.sqrt(sum(v * v for v in values) / samples)
    clipped = sum(1 for v in values if abs(v) >= 32700)
    dbfs = 20 * math.log10(rms / 32768) if rms else -99.0
    note = ""
    if dbfs > -12:
        note = " — too hot, lower the microphone gain"
    elif dbfs < -35:
        note = " — very quiet, raise the microphone gain"
    return f"{samples / sample_rate:.2f}s peak={100 * peak / 32768:.0f}% rms={dbfs:.1f} dBFS clipped={clipped}{note}"


def pcm_to_wav(pcm: bytes, sample_rate: int = STT_SAMPLE_RATE) -> bytes:
    """Wrap raw PCM 16-bit mono in a WAV container (stdlib only)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


@dataclass
class RealtimeOutcome:
    """What a realtime attempt leaves behind for the batch fallback."""

    text: str = ""
    pcm: bytes = b""
    stream_exhausted: bool = False
    # Cleared when the session is lost: the pump keeps buffering the pipeline audio without sending it.
    forward: bool = True
    # Why the realtime attempt produced nothing, so the fallback is never silent.
    reason: str = "empty transcript"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Voxtral STT entity."""
    async_add_entities([VoxtralSttProvider(hass, config_entry)])


class VoxtralSttProvider(stt.SpeechToTextEntity):
    """Voxtral 3 STT provider: realtime session first, file transcription as fallback."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        self.hass = hass
        self._entry = config_entry
        self._attr_name = "Voxtral STT"
        self._attr_unique_id = f"{config_entry.entry_id}-stt"
        self._client = config_entry.runtime_data.client
        self._api_key = config_entry.data.get(CONF_API_KEY, "")

    @property
    def supported_languages(self) -> list[str]:
        return list(STT_SUPPORTED_LANGUAGES)

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        return [stt.AudioFormats.WAV]

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        return [stt.AudioCodecs.PCM]

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        return [stt.AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        return [stt.AudioChannels.CHANNEL_MONO]

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        """Transcribe the pipeline audio: realtime session, then batch, then chat audio."""
        language = normalize_language(
            metadata.language, get_option(self._entry, CONF_STT_LANGUAGE, DEFAULT_STT_LANGUAGE)
        )
        vocabulary = await async_stt_vocabulary(self.hass, self._entry)
        mode = get_option(self._entry, CONF_STT_MODE, DEFAULT_STT_MODE)
        if mode == STT_MODE_REALTIME and language and language not in STT_REALTIME_LANGUAGES:
            _LOGGER.debug(f"[STT] realtime does not support {language!r}, using file transcription")
            mode = STT_MODE_BATCH
        _LOGGER.info(f"[STT] mode={mode} language={language!r} vocabulary={len(vocabulary)} entries")

        try:
            pcm = b""
            if mode == STT_MODE_REALTIME:
                outcome = await self._transcribe_realtime(stream, language, vocabulary)
                if outcome.text:
                    _LOGGER.debug(f"[STT realtime] transcribed {len(outcome.text)} chars")
                    _LOGGER.debug(f"[STT] input {describe_level(outcome.pcm)}")
                    return stt.SpeechResult(outcome.text, stt.SpeechResultState.SUCCESS)
                pcm = outcome.pcm
                if not outcome.stream_exhausted:
                    pcm += await self._drain(stream)
                _LOGGER.warning(f"[STT realtime] no transcript ({outcome.reason}) — trying file transcription")
            else:
                pcm = await self._drain(stream)
            _LOGGER.debug(f"[STT] input {describe_level(pcm)}")

            if not pcm:
                _LOGGER.debug("[STT] empty audio stream, skipping")
                return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

            text = await self._transcribe_batch(pcm, language, vocabulary)
            if text:
                _LOGGER.debug(f"[STT batch] transcribed {len(text)} chars")
                return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)

            if get_option(self._entry, CONF_STT_CHAT_FALLBACK, DEFAULT_STT_CHAT_FALLBACK):
                _LOGGER.warning("[STT batch] returned empty — falling back to chat audio input")
                text = await self._transcribe_chat(pcm)
                if text:
                    _LOGGER.debug(f"[STT chat] transcribed {len(text)} chars")
                    return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)

            _LOGGER.warning("[STT] no speech recognised")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        except Exception as exc:
            _LOGGER.error(f"[STT] exception: {exc}")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

    @staticmethod
    async def _drain(stream: AsyncIterable[bytes]) -> bytes:
        return b"".join([chunk async for chunk in stream])

    # ------------------------------------------------------------------
    # Realtime (websocket, turn detection)
    # ------------------------------------------------------------------

    async def _transcribe_realtime(
        self, stream: AsyncIterable[bytes], language: str | None, vocabulary: list[str]
    ) -> RealtimeOutcome:
        outcome = RealtimeOutcome()
        buffer = bytearray()
        try:
            session = RealtimeSession(
                self._api_key,
                model=STT_MODEL_REALTIME,
                sample_rate=STT_SAMPLE_RATE,
                language=language,
                context_bias=vocabulary,
                turn_detection=turn_detection_preset(
                    get_option(self._entry, CONF_STT_TURN_DETECTION, DEFAULT_STT_TURN_DETECTION)
                ),
                streaming_delay_ms=int(
                    get_option(self._entry, CONF_STT_STREAMING_DELAY_MS, DEFAULT_STT_STREAMING_DELAY_MS)
                ),
            )
            async with asyncio.timeout(REALTIME_TOTAL_TIMEOUT), session:
                sender = asyncio.create_task(self._pump_audio(stream, session, buffer, outcome))
                try:
                    outcome.text = await self._collect_transcript(session, sender, outcome)
                except RealtimeSessionError as exc:
                    outcome.reason = str(exc)
                    # Cancelling the pump would close the pipeline generator and lose the rest of
                    # the utterance: keep draining it into the buffer for the batch fallback.
                    _LOGGER.warning(f"[STT realtime] {exc} — draining the audio for the batch fallback")
                    outcome.forward = False
                    await sender
                finally:
                    if not sender.done():
                        sender.cancel()
                    with suppress(BaseException):
                        await sender
        except (RealtimeSessionError, TimeoutError, OSError, ValueError) as exc:
            outcome.reason = f"{type(exc).__name__}: {exc}"
            _LOGGER.warning(f"[STT realtime] {exc} — falling back to batch transcription")
        outcome.pcm = bytes(buffer)
        return outcome

    @staticmethod
    async def _pump_audio(
        stream: AsyncIterable[bytes], session: RealtimeSession, buffer: bytearray, outcome: RealtimeOutcome
    ) -> None:
        """Forward the pipeline chunks as they arrive, keep a bounded copy for the fallback."""
        async for chunk in stream:
            if len(buffer) < STT_REALTIME_BUFFER_MAX_BYTES:
                buffer.extend(chunk)
            if outcome.forward:
                try:
                    await session.send_audio(chunk)
                except (RealtimeSessionError, RuntimeError) as exc:
                    _LOGGER.debug(f"[STT realtime] stopped forwarding audio: {exc}")
                    outcome.forward = False
        outcome.stream_exhausted = True
        if outcome.forward:
            await session.end_audio()

    async def _collect_transcript(
        self, session: RealtimeSession, sender: asyncio.Task, outcome: RealtimeOutcome
    ) -> str:
        """Consume server events until transcription.done; end the audio early on turn.end."""
        loop = asyncio.get_running_loop()
        events = session.events().__aiter__()
        parts: list[str] = []
        deadline: float | None = None
        try:
            while True:
                if deadline is None and sender.done():
                    # The pipeline audio ended (Home Assistant VAD): input_audio.end was sent.
                    deadline = loop.time() + REALTIME_DONE_TIMEOUT
                timeout = None if deadline is None else max(0.0, deadline - loop.time())
                try:
                    event = await asyncio.wait_for(anext(events), timeout)
                except StopAsyncIteration:
                    raise RealtimeSessionError("connection closed before transcription.done") from None
                except TimeoutError:
                    raise RealtimeSessionError("no transcription.done after input_audio.end") from None

                if isinstance(event, TranscriptionStreamTextDelta):
                    parts.append(event.text)
                elif isinstance(event, TranscriptionStreamDone):
                    text = (event.text or "".join(parts)).strip()
                    _LOGGER.debug(
                        f"[STT realtime] transcription.done after {len(parts)} deltas, "
                        f"{len(text)} chars, language={getattr(event, 'language', '?')!r}"
                    )
                    if not text:
                        outcome.reason = f"server returned an empty transcript after {len(parts)} deltas"
                    return text
                elif isinstance(event, TurnDetectionEndEvent):
                    _LOGGER.debug(f"[STT realtime] turn.end at {event.time_s}s ({event.end_reason})")
                    if not sender.done():
                        sender.cancel()
                    await session.end_audio()
                    deadline = loop.time() + REALTIME_DONE_TIMEOUT
                elif isinstance(event, TurnDetectionEagerEndEvent):
                    self.hass.bus.async_fire(EVENT_STT_EAGER_END, {"entity_id": self.entity_id, "time_s": event.time_s})
                elif isinstance(event, RealtimeTranscriptionError):
                    raise RealtimeSessionError(f"{event.error.message} (code {event.error.code})")
        finally:
            with suppress(BaseException):
                await events.aclose()

    # ------------------------------------------------------------------
    # Batch (file transcription) and chat-audio fallbacks
    # ------------------------------------------------------------------

    async def _transcribe_batch(self, pcm: bytes, language: str | None, vocabulary: list[str]) -> str:
        """Voxtral Mini/Small Transcribe 3 — /v1/audio/transcriptions with a WAV upload."""
        model = STT_BATCH_MODELS.get(
            get_option(self._entry, CONF_STT_BATCH_MODEL, DEFAULT_STT_BATCH_MODEL), STT_MODEL_BATCH_MINI
        )
        kwargs = dict(
            model=model,
            file=MistralFile(file_name="audio.wav", content=pcm_to_wav(pcm), content_type="audio/wav"),
            diarize=False,
        )
        if language:
            kwargs["language"] = language
        if vocabulary:
            kwargs["context_bias"] = list(vocabulary)
        try:
            response = await asyncio.wait_for(self._client.audio.transcriptions.complete_async(**kwargs), BATCH_TIMEOUT)
        except Exception as exc:
            _LOGGER.warning(f"[STT batch] API error: {exc}")
            return ""
        _LOGGER.debug(f"[STT batch] model={model} detected_lang={getattr(response, 'language', '?')!r}")
        return (response.text or "").strip()

    async def _transcribe_chat(self, pcm: bytes) -> str:
        """Last resort: chat completion with audio input (not a transcription model)."""
        audio_b64 = base64.b64encode(pcm_to_wav(pcm)).decode("utf-8")
        try:
            response = await asyncio.wait_for(
                self._client.chat.complete_async(
                    model=STT_MODEL_CHAT_FALLBACK,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_audio", "input_audio": audio_b64},
                                {
                                    "type": "text",
                                    "text": "Transcribe this audio exactly. Return only the transcription, nothing else.",
                                },
                            ],
                        }
                    ],
                ),
                BATCH_TIMEOUT,
            )
        except Exception as exc:
            _LOGGER.warning(f"[STT chat] API error: {exc}")
            return ""
        return (response.choices[0].message.content or "").strip()
