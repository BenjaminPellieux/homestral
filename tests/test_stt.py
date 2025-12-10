"""
Tests unitaires pour le module stt.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homestral.stt import VoxtralSttProvider
from homestral.errors import AudioProcessingError


@pytest.mark.asyncio
@patch('homestral.stt.AudioSegment')
@patch('homestral.stt.base64.b64encode')
@patch('homestral.stt.io.BytesIO')
async def test_async_process_audio_stream_success(mock_bytesio, mock_b64encode, mock_audio_segment):
    """Test le traitement réussi d'un flux audio."""
    # Configurer les mocks
    mock_audio_segment_instance = MagicMock()
    mock_audio_segment_instance.raw_data = b"test audio data"
    mock_audio_segment.return_value = mock_audio_segment_instance
    mock_b64encode.return_value.decode.return_value = "test_base64_audio"
    mock_bytesio_instance = MagicMock()
    mock_bytesio.return_value = mock_bytesio_instance
    mock_bytesio_instance.read.return_value = b"test wav data"
    
    # Créer un mock pour le client Mistral
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Test transcription"
    mock_client.chat.complete = MagicMock(return_value=mock_response)
    
    # Créer une instance de VoxtralSttProvider
    provider = VoxtralSttProvider(None, MagicMock())
    provider._client = mock_client
    
    # Créer un flux audio mock asynchrone
    async def mock_audio_stream():
        yield b"test audio data"
    
    # Appeler la méthode async_process_audio_stream
    result = await provider.async_process_audio_stream(None, mock_audio_stream())
    
    # Vérifier que les appels ont été faits correctement
    mock_audio_segment.assert_called_once()
    mock_b64encode.assert_called_once()
    mock_bytesio.assert_called_once()
    
    # Vérifier que le résultat est correct
    assert result.text == "Test transcription"
    assert result.result.name == "SUCCESS"


@pytest.mark.asyncio
async def test_async_process_audio_stream_error():
    """Test le traitement échoué d'un flux audio."""
    # Créer un mock pour le client Mistral
    mock_client = MagicMock()
    mock_client.chat.complete = AsyncMock(side_effect=Exception("API Error"))
    
    # Créer une instance de VoxtralSttProvider
    provider = VoxtralSttProvider(None, MagicMock())
    provider._client = mock_client
    
    # Créer un flux audio mock asynchrone
    async def mock_audio_stream():
        yield b"test audio data"
    
    # Appeler la méthode async_process_audio_stream
    result = await provider.async_process_audio_stream(None, mock_audio_stream())
    
    # Vérifier que le résultat est correct
    assert result.text is None
    assert result.result.name == "ERROR"


def test_supported_languages():
    """Test les langues supportées."""
    provider = VoxtralSttProvider(None, MagicMock())
    assert provider.supported_languages == ["en", "fr"]


def test_supported_formats():
    """Test les formats audio supportés."""
    provider = VoxtralSttProvider(None, MagicMock())
    from homeassistant.components import stt
    assert provider.supported_formats == [stt.AudioFormats.WAV]


def test_supported_codecs():
    """Test les codecs audio supportés."""
    provider = VoxtralSttProvider(None, MagicMock())
    from homeassistant.components import stt
    assert provider.supported_codecs == [stt.AudioCodecs.PCM]


def test_supported_bit_rates():
    """Test les bitrates audio supportés."""
    provider = VoxtralSttProvider(None, MagicMock())
    from homeassistant.components import stt
    assert provider.supported_bit_rates == [stt.AudioBitRates.BITRATE_16]


def test_supported_sample_rates():
    """Test les sample rates audio supportés."""
    provider = VoxtralSttProvider(None, MagicMock())
    from homeassistant.components import stt
    assert provider.supported_sample_rates == [stt.AudioSampleRates.SAMPLERATE_16000]


def test_supported_channels():
    """Test les canaux audio supportés."""
    provider = VoxtralSttProvider(None, MagicMock())
    from homeassistant.components import stt
    assert provider.supported_channels == [stt.AudioChannels.CHANNEL_MONO]


if __name__ == "__main__":
    pytest.main([__file__])