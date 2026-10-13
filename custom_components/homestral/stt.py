import asyncio
import base64
import io
from collections.abc import AsyncIterable

from homeassistant.components import stt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

try:
    from mistralai.models import File as MistralFile
except ImportError:
    from mistralai.client.models import File as MistralFile

from pydub import AudioSegment

from .const import DEFAULT_STT_MODEL, HOME_AUTOMATION_VOCAB
from .logging_config import get_logger

_LOGGER = get_logger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Voxtral STT entity."""
    async_add_entities([VoxtralSttProvider(hass, config_entry)])


class VoxtralSttProvider(stt.SpeechToTextEntity):
    """Voxtral STT provider — tries Transcribe 2 API, falls back to chat API."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        self.hass = hass
        self._attr_name = "Voxtral STT"
        self._attr_unique_id = f"{config_entry.entry_id}-stt"
        self._client = config_entry.runtime_data

    @property
    def supported_languages(self) -> list[str]:
        return ["en", "fr", "zh", "hi", "es", "ar", "pt", "ru", "de", "ja", "ko", "it", "nl"]

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

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        """Transcribe audio — V2 API first, V1 chat API as fallback."""
        audio_bytes = b""
        try:
            audio_bytes = b"".join([chunk async for chunk in stream])

            if not audio_bytes:
                _LOGGER.debug("[STT] empty audio stream, skipping")
                return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

            # Wrap raw PCM in WAV container
            audio_segment = AudioSegment(
                audio_bytes,
                sample_width=2,
                frame_rate=16000,
                channels=1,
            )
            buf = io.BytesIO()
            audio_segment.export(buf, format="wav")
            wav_bytes = buf.getvalue()

            _LOGGER.info(
                f"[STT] captured: {len(audio_bytes)} PCM bytes → {len(wav_bytes)} WAV bytes | "
                f"lang={metadata.language!r} model={DEFAULT_STT_MODEL}"
            )

            # ── Try Voxtral Transcribe 2 (V2 API) ──────────────────────────────
            text = await self._transcribe_v2(wav_bytes, metadata.language)

            if text:
                _LOGGER.info(f"[STT V2] ✓ transcribed: {text!r}")
                return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)

            _LOGGER.warning("[STT V2] returned empty — falling back to V1 chat API")

            # ── Fallback: Voxtral V1 (chat API with base64 audio) ──────────────
            text = await self._transcribe_v1(wav_bytes, audio_bytes)

            if text:
                _LOGGER.info(f"[STT V1] ✓ transcribed: {text!r}")
                return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)

            _LOGGER.warning("[STT V1] also returned empty — no speech detected")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        except Exception as exc:
            _LOGGER.error(f"[STT] exception: {exc}")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

    # ──────────────────────────────────────────────────────────────────────────
    # Voxtral Transcribe 2 — /v1/audio/transcriptions (multipart file upload)
    # ──────────────────────────────────────────────────────────────────────────
    async def _transcribe_v2(self, wav_bytes: bytes, language: str) -> str:
        """Voxtral Transcribe 2 — /v1/audio/transcriptions with raw bytes (Pydantic requires bytes, not BytesIO)."""
        try:
            audio_file = MistralFile(
                file_name="audio.wav",
                content=wav_bytes,  # raw bytes — BytesIO rejected by Pydantic
                content_type="audio/wav",
            )
            # language omitted intentionally: sending 'fr' caused silent empty responses;
            # auto-detect is more reliable across accents
            _LOGGER.debug("[STT V2] calling transcriptions.complete (auto-detect lang)")
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.audio.transcriptions.complete(
                    model=DEFAULT_STT_MODEL,
                    file=audio_file,
                    # Voxtral 2 context biasing — boosts home-automation vocabulary
                    # accuracy. API requires single words (pattern ^[^,\s]+$),
                    # see HOME_AUTOMATION_VOCAB.
                    context_bias=HOME_AUTOMATION_VOCAB,
                    diarize=False,
                ),
            )
            _LOGGER.debug(
                f"[STT V2] text={response.text!r} "
                f"detected_lang={getattr(response, 'language', '?')!r} "
                f"usage={getattr(response, 'usage', '?')}"
            )
            return (response.text or "").strip()
        except Exception as exc:
            _LOGGER.warning(f"[STT V2] API error: {exc}")
            return ""

    async def _transcribe_v1(self, wav_bytes: bytes, raw_pcm: bytes) -> str:
        """Voxtral V1 — chat completions with base64 audio (model: voxtral-small-latest)."""
        try:
            audio_b64 = base64.b64encode(wav_bytes).decode("utf-8")
            _LOGGER.debug(f"[STT V1] calling chat.complete b64_len={len(audio_b64)}")
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.chat.complete(
                    model="voxtral-small-latest",  # the only model supporting input_audio in chat router
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
            )
            text = response.choices[0].message.content or ""
            _LOGGER.debug(f"[STT V1] response: {text!r}")
            return text.strip()
        except Exception as exc:
            _LOGGER.warning(f"[STT V1] API error: {exc}")
            return ""
