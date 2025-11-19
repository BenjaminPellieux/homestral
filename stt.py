from collections.abc import AsyncIterable
import logging
from homeassistant.components import stt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from mistralai import Mistral
import base64
import aiohttp

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Voxtral speech-to-text."""
    async_add_entities([VoxtralSttProvider(config_entry)])

class VoxtralSttProvider(stt.SpeechToTextEntity):
    """Voxtral speech-to-text provider."""

    def __init__(self, config_entry: ConfigEntry):
        """Set up provider."""
        self.config_entry = config_entry
        self._attr_name = "Voxtral STT"
        self._attr_unique_id = f"{config_entry.entry_id}-stt"

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return ["fr", "en"]

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
        """Process an audio stream to Voxtral STT service."""
        try:
            # Lire le flux audio et le convertir en base64
            audio_bytes = b''.join([chunk async for chunk in stream])
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

            # Appeler l'API Voxtral pour la reconnaissance vocale
            api_key = self.config_entry.data["api_key"]
            client = Mistral(api_key=api_key)
            response = client.chat.complete(
                model="voxtral-mini-latest",
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
                    ]
                }],
            )

            # Extraire le texte reconnu
            text = response.choices[0].message.content
            return stt.SpeechResult(
                text,
                stt.SpeechResultState.SUCCESS,
            )
        except Exception as e:
            _LOGGER.error(f"Error processing audio stream: {e}")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
