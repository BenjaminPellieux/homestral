"""
Tests unitaires pour le module stt.py.

Le provider Voxtral essaie d'abord l'API Transcribe 2
(``client.audio.transcriptions.complete``) puis retombe sur l'API chat V1
(``client.chat.complete`` avec audio base64). Les tests mockent le client
Mistral et verifient les deux chemins.
"""

from unittest.mock import MagicMock

import pytest
from homeassistant.components import stt

from custom_components.homestral.const import DEFAULT_STT_MODEL, HOME_AUTOMATION_VOCAB
from custom_components.homestral.stt import VoxtralSttProvider


def _make_provider():
    """Construit un provider avec un client Mistral mocke."""
    provider = VoxtralSttProvider(None, MagicMock())
    provider._client = MagicMock()
    return provider


def _make_metadata(language="fr"):
    metadata = MagicMock()
    metadata.language = language
    return metadata


# 1600 octets = 50 ms de PCM 16 bits mono a 16 kHz (longueur paire requise
# par pydub : multiple de sample_width * channels)
AUDIO_CHUNK = b"\x00\x01" * 800


async def _audio_stream(*chunks):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_async_process_audio_stream_v2_success():
    """V2: client.audio.transcriptions.complete est appele avec le modele Voxtral 2."""
    provider = _make_provider()

    mock_response = MagicMock()
    mock_response.text = "Allume la lumière du salon"
    provider._client.audio.transcriptions.complete = MagicMock(return_value=mock_response)

    result = await provider.async_process_audio_stream(_make_metadata(), _audio_stream(AUDIO_CHUNK))

    assert result.text == "Allume la lumière du salon"
    assert result.result == stt.SpeechResultState.SUCCESS

    provider._client.audio.transcriptions.complete.assert_called_once()
    kwargs = provider._client.audio.transcriptions.complete.call_args.kwargs
    assert kwargs["model"] == DEFAULT_STT_MODEL
    assert kwargs["context_bias"] == HOME_AUTOMATION_VOCAB
    assert kwargs["diarize"] is False
    # Le fichier envoye est un conteneur WAV construit a partir des octets audio
    audio_file = kwargs["file"]
    assert audio_file.file_name == "audio.wav"
    assert audio_file.content_type == "audio/wav"
    assert audio_file.content.startswith(b"RIFF")
    # L'API V1 (chat) n'est pas utilisee quand V2 reussit
    provider._client.chat.complete.assert_not_called()


@pytest.mark.asyncio
async def test_async_process_audio_stream_v1_fallback():
    """V2 indisponible (AttributeError) -> fallback sur l'API chat V1."""
    provider = _make_provider()

    # Simule un SDK sans l'endpoint Transcribe 2
    provider._client.audio.transcriptions.complete = MagicMock(
        side_effect=AttributeError("'Transcriptions' object has no attribute 'complete'")
    )

    v1_response = MagicMock()
    v1_response.choices = [MagicMock()]
    v1_response.choices[0].message.content = "Éteins la lumière"
    provider._client.chat.complete = MagicMock(return_value=v1_response)

    result = await provider.async_process_audio_stream(_make_metadata(), _audio_stream(AUDIO_CHUNK))

    assert result.text == "Éteins la lumière"
    assert result.result == stt.SpeechResultState.SUCCESS

    provider._client.chat.complete.assert_called_once()
    chat_kwargs = provider._client.chat.complete.call_args.kwargs
    assert chat_kwargs["model"] == "voxtral-small-latest"
    # Le message contient l'audio encode en base64
    content = chat_kwargs["messages"][0]["content"]
    audio_chunks = [c for c in content if c.get("type") == "input_audio"]
    assert len(audio_chunks) == 1
    assert isinstance(audio_chunks[0]["input_audio"], str)


@pytest.mark.asyncio
async def test_async_process_audio_stream_error():
    """Les erreurs API V2 et V1 propagated -> resultat ERROR."""
    provider = _make_provider()
    provider._client.audio.transcriptions.complete = MagicMock(side_effect=Exception("API Error"))
    provider._client.chat.complete = MagicMock(side_effect=Exception("API Error"))

    result = await provider.async_process_audio_stream(_make_metadata(), _audio_stream(AUDIO_CHUNK))

    assert result.text is None
    assert result.result == stt.SpeechResultState.ERROR


@pytest.mark.asyncio
async def test_async_process_audio_stream_empty_stream():
    """Un flux audio vide -> resultat ERROR sans appel API."""
    provider = _make_provider()

    result = await provider.async_process_audio_stream(_make_metadata(), _audio_stream())

    assert result.text is None
    assert result.result == stt.SpeechResultState.ERROR
    provider._client.audio.transcriptions.complete.assert_not_called()
    provider._client.chat.complete.assert_not_called()


def test_supported_languages():
    """Test les langues supportées (13 langues Voxtral)."""
    provider = _make_provider()
    assert len(provider.supported_languages) == 13
    assert "en" in provider.supported_languages
    assert "fr" in provider.supported_languages


def test_supported_formats():
    """Test les formats audio supportés."""
    provider = _make_provider()
    assert provider.supported_formats == [stt.AudioFormats.WAV]


def test_supported_codecs():
    """Test les codecs audio supportés."""
    provider = _make_provider()
    assert provider.supported_codecs == [stt.AudioCodecs.PCM]


def test_supported_bit_rates():
    """Test les bitrates audio supportés."""
    provider = _make_provider()
    assert provider.supported_bit_rates == [stt.AudioBitRates.BITRATE_16]


def test_supported_sample_rates():
    """Test les sample rates audio supportés."""
    provider = _make_provider()
    assert provider.supported_sample_rates == [stt.AudioSampleRates.SAMPLERATE_16000]


def test_supported_channels():
    """Test les canaux audio supportés."""
    provider = _make_provider()
    assert provider.supported_channels == [stt.AudioChannels.CHANNEL_MONO]


if __name__ == "__main__":
    pytest.main([__file__])
