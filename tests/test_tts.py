"""Tests for the Voxtral TTS 3 entity.

Regression: the speech API returns the audio as a base64 string
(``SpeechResponse.audio_data``); the entity must decode it before handing the
bytes to Home Assistant. Voices are Voxtral 3 preset ids chosen by language
unless the pipeline passes a ``voice`` option.
"""

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components import tts

from custom_components.homestral.const import DEFAULT_TTS_FORMAT, DEFAULT_TTS_MODEL, TTS_VOICES
from custom_components.homestral.tts import VoxtralTtsProvider, decode_audio, language_key, resolve_voice

WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 24


def _make_provider(audio_data=None, side_effect=None):
    provider = VoxtralTtsProvider(MagicMock(), MagicMock(entry_id="entry"))
    provider._client = MagicMock()
    if side_effect is not None:
        provider._client.audio.speech.complete_async = AsyncMock(side_effect=side_effect)
    else:
        response = MagicMock()
        response.audio_data = audio_data if audio_data is not None else base64.b64encode(WAV_BYTES).decode()
        provider._client.audio.speech.complete_async = AsyncMock(return_value=response)
    return provider


@pytest.mark.asyncio
async def test_get_tts_audio_decodes_base64_and_uses_voxtral3_defaults():
    provider = _make_provider()

    extension, audio = await provider.async_get_tts_audio("Bonjour", "fr", {})

    assert extension == DEFAULT_TTS_FORMAT
    assert audio == WAV_BYTES
    kwargs = provider._client.audio.speech.complete_async.call_args.kwargs
    assert kwargs["model"] == DEFAULT_TTS_MODEL
    assert kwargs["input"] == "Bonjour"
    assert kwargs["response_format"] == DEFAULT_TTS_FORMAT
    assert kwargs["voice_id"] == TTS_VOICES["fr"][0][0]


@pytest.mark.asyncio
async def test_get_tts_audio_picks_voice_by_language():
    provider = _make_provider()

    await provider.async_get_tts_audio("Hello", "en-GB", None)

    assert provider._client.audio.speech.complete_async.call_args.kwargs["voice_id"] == TTS_VOICES["en"][0][0]


@pytest.mark.asyncio
async def test_get_tts_audio_voice_option_overrides_language_default():
    provider = _make_provider()

    await provider.async_get_tts_audio("Bonjour", "fr", {tts.ATTR_VOICE: "voice_3137"})

    assert provider._client.audio.speech.complete_async.call_args.kwargs["voice_id"] == "voice_3137"


@pytest.mark.asyncio
async def test_get_tts_audio_unknown_language_falls_back_to_default_voice():
    provider = _make_provider()

    await provider.async_get_tts_audio("Hej", "sv", {})

    assert provider._client.audio.speech.complete_async.call_args.kwargs["voice_id"] == TTS_VOICES["fr"][0][0]


@pytest.mark.asyncio
async def test_get_tts_audio_sdk_error_returns_none():
    provider = _make_provider(side_effect=RuntimeError("API down"))

    assert await provider.async_get_tts_audio("Bonjour", "fr", {}) == (None, None)


@pytest.mark.asyncio
async def test_get_tts_audio_accepts_raw_bytes_payload():
    """If the SDK ever returns raw bytes, they are passed through untouched."""
    provider = _make_provider(audio_data=WAV_BYTES)

    _extension, audio = await provider.async_get_tts_audio("Bonjour", "fr", {})

    assert audio == WAV_BYTES


def test_supported_voices_per_language():
    provider = _make_provider()

    voices = provider.async_get_supported_voices("fr-FR")

    assert voices is not None
    assert [v.voice_id for v in voices] == [voice_id for voice_id, _name in TTS_VOICES["fr"]]
    assert all(isinstance(v, tts.Voice) for v in voices)
    assert provider.async_get_supported_voices("sv") is None


def test_entity_declares_voice_option_and_languages():
    provider = _make_provider()

    assert provider.supported_options == [tts.ATTR_VOICE]
    assert provider.default_language == "fr"
    assert set(provider.supported_languages) == set(TTS_VOICES)


@pytest.mark.parametrize(
    "language,expected",
    [("fr", "fr"), ("fr-FR", "fr"), ("en_GB", "en"), ("EN-us", "en"), ("sv", None), (None, None), ("", None)],
)
def test_language_key(language, expected):
    assert language_key(language) == expected


def test_resolve_voice_and_decode_helpers():
    assert resolve_voice("de", None) == TTS_VOICES["de"][0][0]
    assert resolve_voice("de", {tts.ATTR_VOICE: "voice_999"}) == "voice_999"
    assert decode_audio(base64.b64encode(b"abc").decode()) == b"abc"
    assert decode_audio(b"abc") == b"abc"
