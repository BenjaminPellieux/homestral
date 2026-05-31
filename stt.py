from collections.abc import AsyncIterable
import asyncio
import io
from homeassistant.components import stt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
try:
    from mistralai import Mistral
    from mistralai.models import File as MistralFile
except ImportError:
    from mistralai.client import Mistral  # HA musllinux wheel (namespace package)
    from mistralai.client.models import File as MistralFile
from pydub import AudioSegment
from .const import DEFAULT_STT_MODEL, HOME_AUTOMATION_VOCAB
from .errors import AudioProcessingError
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
    """Voxtral speech-to-text provider using Voxtral Transcribe 2 API."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Set up provider."""
        self.hass = hass
        self._attr_name = "Voxtral STT"
        self._attr_unique_id = f"{config_entry.entry_id}-stt"
        self._client = Mistral(api_key=config_entry.data["api_key"])

    @property
    def supported_languages(self) -> list[str]:
        """Return languages supported by Voxtral Transcribe 2 (13 languages)."""
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
        """Process an audio stream using Voxtral Transcribe 2 /v1/audio/transcriptions."""
        audio_bytes = b""
        try:
            audio_bytes = b"".join([chunk async for chunk in stream])

            if not audio_bytes:
                _LOGGER.debug("[STT] empty audio stream, skipping API call")
                return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

            # Convert raw PCM to WAV container
            audio_segment = AudioSegment(
                audio_bytes,
                sample_width=2,
                frame_rate=16000,
                channels=1,
            )
            buf = io.BytesIO()
            audio_segment.export(buf, format="wav")
            wav_bytes = buf.getvalue()

            _LOGGER.info(f"[STT] audio captured: {len(audio_bytes)} raw bytes → {len(wav_bytes)} WAV bytes")

            # Voxtral Transcribe 2: audio.transcriptions.complete (SDK 2.4.8)
            language = metadata.language if metadata.language and metadata.language != "auto" else None
            audio_file = MistralFile(
                file_name="audio.wav",
                content=wav_bytes,
                content_type="audio/wav",
            )
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.audio.transcriptions.complete(
                    model=DEFAULT_STT_MODEL,
                    file=audio_file,
                    language=language,
                    context_bias=HOME_AUTOMATION_VOCAB,
                ),
            )

            text = response.text
            _LOGGER.info(f"[STT] transcribed: {text!r}")

            if not text or not text.strip():
                _LOGGER.debug("[STT] empty transcription (silence/noise), returning ERROR")
                return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

            return stt.SpeechResult(text.strip(), stt.SpeechResultState.SUCCESS)

        except Exception as e:
            error = AudioProcessingError(
                message=f"Error processing audio stream: {e}",
                code="AUDIO_PROCESSING_ERROR",
                details={"error": str(e), "audio_bytes_length": len(audio_bytes)},
            )
            _LOGGER.error(f"Error processing audio stream: {error}")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
