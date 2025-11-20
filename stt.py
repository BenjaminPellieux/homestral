from collections.abc import AsyncIterable
import logging
import base64
import io
from homeassistant.components import stt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from mistralai import Mistral
from pydub import AudioSegment
from .const import *

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Voxtral STT entity."""
    async_add_entities([VoxtralSttProvider(hass, config_entry)])

class VoxtralSttProvider(stt.SpeechToTextEntity):
    """Voxtral speech-to-text provider."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Set up provider."""
        self.hass = hass
        self._attr_name = "Voxtral STT"
        self._attr_unique_id = f"{config_entry.entry_id}-stt"
        self._client = Mistral(api_key=config_entry.data["api_key"])

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return ["en", "fr"]

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        """Return a list of supported formats."""
        return [stt.AudioFormats.WAV]

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        """Return a list of supported codecs."""
        return [stt.AudioCodecs.PCM]

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        """Return a list of supported bitrates."""
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        """Return a list of supported samplerates."""
        return [stt.AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        """Return a list of supported channels."""
        return [stt.AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        """Process an audio stream to STT service."""
        try:
            # Capturer l'audio et l'encoder en WAV
            audio_bytes = b''.join([chunk async for chunk in stream])
            audio_segment = AudioSegment(
                audio_bytes,
                sample_width=2,
                frame_rate=16000,
                channels=1
            )
            wav_audio = io.BytesIO()
            audio_segment.export(wav_audio, format="wav")
            wav_audio.seek(0)
            wav_bytes = wav_audio.read()
            audio_base64 = base64.b64encode(wav_bytes).decode('utf-8')
            _LOGGER.info(f"\n\n[DEBUG] : {len(audio_bytes)=} {len(audio_base64)=}")

            # Envoyer l'audio à l'API Voxtral pour la transcription
            response = self._client.chat.complete(
                model=DEFAULT_STT_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": audio_base64,
                        },
                        {
                            "type": "text",
                            "text": "Transcribe this audio.",
                        },
                    ],
                }],
            )
            # Extraire le texte transcrit
            _LOGGER.info(f"\n\n[DEBUG] : {response=}")
            text = response.choices[0].message.content
            return stt.SpeechResult(
                text,
                stt.SpeechResultState.SUCCESS,
            )
        except Exception as e:
            _LOGGER.error(f"Error processing audio stream: {e}")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
