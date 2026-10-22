"""Tests for the Voxtral 3 STT entity (stt.py).

The realtime session is replaced by a scripted fake (no network), the batch
and chat fallbacks by mocked SDK calls. Covers: realtime happy path, early end
on turn.end, eager-end event, fallback on realtime errors with the captured
audio, batch mode, language handling and the chat fallback option.
"""

import asyncio
import io
import wave
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components import stt
from mistralai.client.models import (
    RealtimeTranscriptionError,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
    TurnDetectionEagerEndEvent,
    TurnDetectionEndEvent,
)

from custom_components.homestral import stt as stt_mod
from custom_components.homestral.const import (
    CONF_STT_BATCH_MODEL,
    CONF_STT_CHAT_FALLBACK,
    CONF_STT_LANGUAGE,
    CONF_STT_MODE,
    CONF_STT_STREAMING_DELAY_MS,
    CONF_STT_TURN_DETECTION,
    EVENT_STT_EAGER_END,
    STT_LANGUAGE_AUTO,
    STT_MODE_BATCH,
    STT_MODEL_BATCH_MINI,
    STT_MODEL_BATCH_SMALL,
    STT_MODEL_CHAT_FALLBACK,
    STT_MODEL_REALTIME,
    STT_SUPPORTED_LANGUAGES,
)
from custom_components.homestral.stt import VoxtralSttProvider, normalize_language, pcm_to_wav
from custom_components.homestral.voxtral_realtime import TURN_PRESETS, RealtimeSessionError

# 1600 bytes = 50 ms of PCM 16-bit mono at 16 kHz
CHUNK = b"\x00\x01" * 800
VOCABULARY = ["volet roulant", "Salon"]


def _delta(text):
    return TranscriptionStreamTextDelta.model_validate({"type": "transcription.text.delta", "text": text})


def _done(text):
    return TranscriptionStreamDone.model_validate(
        {
            "type": "transcription.done",
            "text": text,
            "language": "fr",
            "model": STT_MODEL_REALTIME,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )


def _turn_end():
    return TurnDetectionEndEvent.model_validate({"type": "turn.end", "time_s": 1.2, "end_reason": "threshold"})


def _eager_end():
    return TurnDetectionEagerEndEvent.model_validate({"type": "turn.eager_end", "time_s": 0.9})


def _error():
    return RealtimeTranscriptionError.model_validate({"type": "error", "error": {"message": "boom", "code": 500}})


class FakeSession:
    """Scripted stand-in for voxtral_realtime.RealtimeSession."""

    instances: list = []
    script: list = []
    fail_connect = False

    def __init__(self, api_key, **kwargs):
        self.api_key = api_key
        self.kwargs = kwargs
        self.sent: list[bytes] = []
        self.ended = False
        self.closed = False
        FakeSession.instances.append(self)

    @property
    def audio_ended(self):
        return self.ended

    async def __aenter__(self):
        if FakeSession.fail_connect:
            raise RealtimeSessionError("connect failed")
        return self

    async def __aexit__(self, *exc):
        self.closed = True

    async def send_audio(self, pcm):
        self.sent.append(bytes(pcm))

    async def end_audio(self):
        self.ended = True

    async def events(self):
        for item in self.script:
            if item == "WAIT_END":
                while not self.ended:
                    await asyncio.sleep(0)
                continue
            if item == "WAIT_SENT":
                while not self.sent:
                    await asyncio.sleep(0)
                continue
            yield item


@pytest.fixture
def fake_session(monkeypatch):
    FakeSession.instances = []
    FakeSession.script = []
    FakeSession.fail_connect = False
    monkeypatch.setattr(stt_mod, "RealtimeSession", FakeSession)
    monkeypatch.setattr(stt_mod, "async_stt_vocabulary", AsyncMock(return_value=list(VOCABULARY)))
    return FakeSession


def _make_provider(options=None):
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.data = {"api_key": "sk-test"}
    entry.options = options or {}
    provider = VoxtralSttProvider(hass, entry)
    provider._client = MagicMock()
    provider._client.audio.transcriptions.complete_async = AsyncMock(
        return_value=MagicMock(text="texte batch", language="fr")
    )
    provider._client.chat.complete_async = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="texte chat"))])
    )
    return provider


def _metadata(language="fr-FR"):
    metadata = MagicMock()
    metadata.language = language
    return metadata


async def _stream(*chunks):
    for chunk in chunks:
        yield chunk
        await asyncio.sleep(0)


async def _endless_stream(count=100):
    for _ in range(count):
        yield CHUNK
        await asyncio.sleep(0)


def _wav_frames(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (16000, 2, 1)
        return wav.readframes(wav.getnframes())


# ---------------------------------------------------------------------------
# Realtime path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_realtime_success_streams_all_chunks_and_uses_options(fake_session):
    fake_session.script = [_delta("Allume"), _delta(" la lumière"), "WAIT_END", _done("Allume la lumière")]
    provider = _make_provider({CONF_STT_TURN_DETECTION: "aggressive", CONF_STT_STREAMING_DELAY_MS: 960})

    result = await provider.async_process_audio_stream(_metadata("fr-FR"), _stream(CHUNK, CHUNK, CHUNK))

    assert result.result == stt.SpeechResultState.SUCCESS
    assert result.text == "Allume la lumière"
    session = fake_session.instances[0]
    assert session.api_key == "sk-test"
    assert session.kwargs["model"] == STT_MODEL_REALTIME
    assert session.kwargs["sample_rate"] == 16000
    assert session.kwargs["language"] == "fr"
    assert session.kwargs["context_bias"] == VOCABULARY
    assert session.kwargs["streaming_delay_ms"] == 960
    assert session.kwargs["turn_detection"].model_dump(exclude_unset=True) == TURN_PRESETS["aggressive"]
    assert session.sent == [CHUNK, CHUNK, CHUNK]
    assert session.ended and session.closed
    provider._client.audio.transcriptions.complete_async.assert_not_called()


@pytest.mark.asyncio
async def test_realtime_turn_end_stops_consuming_the_pipeline_audio(fake_session):
    fake_session.script = [_delta("Allume"), _turn_end(), "WAIT_END", _done("Allume")]
    provider = _make_provider()

    result = await provider.async_process_audio_stream(_metadata(), _endless_stream(100))

    assert result.text == "Allume"
    session = fake_session.instances[0]
    assert session.ended
    assert len(session.sent) < 100


@pytest.mark.asyncio
async def test_realtime_eager_end_fires_home_assistant_event(fake_session):
    fake_session.script = [_eager_end(), _delta("ok"), "WAIT_END", _done("ok")]
    provider = _make_provider()

    await provider.async_process_audio_stream(_metadata(), _stream(CHUNK))

    provider.hass.bus.async_fire.assert_called_once()
    event_type, data = provider.hass.bus.async_fire.call_args.args
    assert event_type == EVENT_STT_EAGER_END
    assert data["time_s"] == 0.9


@pytest.mark.asyncio
async def test_realtime_done_text_falls_back_to_joined_deltas(fake_session):
    fake_session.script = [_delta("Bon"), _delta("jour"), "WAIT_END", _done("")]
    provider = _make_provider()

    result = await provider.async_process_audio_stream(_metadata(), _stream(CHUNK))

    assert result.text == "Bonjour"


@pytest.mark.asyncio
async def test_realtime_turn_detection_off_sends_no_config(fake_session):
    fake_session.script = ["WAIT_END", _done("ok")]
    provider = _make_provider({CONF_STT_TURN_DETECTION: "off"})

    await provider.async_process_audio_stream(_metadata(), _stream(CHUNK))

    assert fake_session.instances[0].kwargs["turn_detection"] is None


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_realtime_error_event_falls_back_to_batch_with_all_the_audio(fake_session):
    # The error arrives after the first chunk was forwarded: the rest of the utterance must still
    # reach the batch fallback (the pipeline generator is drained, not cancelled).
    fake_session.script = ["WAIT_SENT", _error()]
    provider = _make_provider()

    result = await provider.async_process_audio_stream(_metadata("fr"), _stream(CHUNK, CHUNK, CHUNK))

    assert result.result == stt.SpeechResultState.SUCCESS
    assert result.text == "texte batch"
    session = fake_session.instances[0]
    assert 1 <= len(session.sent) < 3
    assert not session.ended
    kwargs = provider._client.audio.transcriptions.complete_async.call_args.kwargs
    assert kwargs["model"] == STT_MODEL_BATCH_MINI
    assert kwargs["language"] == "fr"
    assert kwargs["context_bias"] == VOCABULARY
    assert kwargs["diarize"] is False
    assert kwargs["file"].file_name == "audio.wav"
    assert _wav_frames(kwargs["file"].content) == CHUNK * 3


@pytest.mark.asyncio
async def test_realtime_connect_failure_falls_back_to_batch(fake_session):
    fake_session.fail_connect = True
    provider = _make_provider()

    result = await provider.async_process_audio_stream(_metadata(), _stream(CHUNK, CHUNK))

    assert result.text == "texte batch"
    assert (
        _wav_frames(provider._client.audio.transcriptions.complete_async.call_args.kwargs["file"].content) == CHUNK * 2
    )


@pytest.mark.asyncio
async def test_realtime_closed_before_done_falls_back_to_batch(fake_session):
    fake_session.script = [_delta("Allu")]  # the server closes without transcription.done
    provider = _make_provider()

    result = await provider.async_process_audio_stream(_metadata(), _stream(CHUNK))

    assert result.text == "texte batch"


@pytest.mark.asyncio
async def test_batch_mode_skips_realtime_and_honours_small_model(fake_session):
    provider = _make_provider({CONF_STT_MODE: STT_MODE_BATCH, CONF_STT_BATCH_MODEL: "small"})

    result = await provider.async_process_audio_stream(_metadata("en-GB"), _stream(CHUNK, CHUNK))

    assert result.text == "texte batch"
    assert fake_session.instances == []
    kwargs = provider._client.audio.transcriptions.complete_async.call_args.kwargs
    assert kwargs["model"] == STT_MODEL_BATCH_SMALL
    assert kwargs["language"] == "en"


@pytest.mark.asyncio
async def test_language_auto_omits_the_language_everywhere(fake_session):
    fake_session.script = [_error()]
    provider = _make_provider({CONF_STT_LANGUAGE: STT_LANGUAGE_AUTO})

    await provider.async_process_audio_stream(_metadata("fr-FR"), _stream(CHUNK))

    assert fake_session.instances[0].kwargs["language"] is None
    assert "language" not in provider._client.audio.transcriptions.complete_async.call_args.kwargs


@pytest.mark.asyncio
async def test_chat_fallback_only_when_enabled(fake_session):
    fake_session.fail_connect = True
    provider = _make_provider()
    provider._client.audio.transcriptions.complete_async = AsyncMock(return_value=MagicMock(text=""))

    result = await provider.async_process_audio_stream(_metadata(), _stream(CHUNK))
    assert result.result == stt.SpeechResultState.ERROR
    provider._client.chat.complete_async.assert_not_called()

    provider = _make_provider({CONF_STT_CHAT_FALLBACK: True})
    provider._client.audio.transcriptions.complete_async = AsyncMock(return_value=MagicMock(text=""))

    result = await provider.async_process_audio_stream(_metadata(), _stream(CHUNK))
    assert result.result == stt.SpeechResultState.SUCCESS
    assert result.text == "texte chat"
    assert provider._client.chat.complete_async.call_args.kwargs["model"] == STT_MODEL_CHAT_FALLBACK


@pytest.mark.asyncio
async def test_batch_api_error_returns_error_result(fake_session):
    provider = _make_provider({CONF_STT_MODE: STT_MODE_BATCH})
    provider._client.audio.transcriptions.complete_async = AsyncMock(side_effect=RuntimeError("API down"))

    result = await provider.async_process_audio_stream(_metadata(), _stream(CHUNK))

    assert result.result == stt.SpeechResultState.ERROR
    assert result.text is None


@pytest.mark.asyncio
async def test_empty_stream_returns_error_without_api_calls(fake_session):
    fake_session.fail_connect = True
    provider = _make_provider()

    result = await provider.async_process_audio_stream(_metadata(), _stream())

    assert result.result == stt.SpeechResultState.ERROR
    provider._client.audio.transcriptions.complete_async.assert_not_called()


# ---------------------------------------------------------------------------
# Helpers and entity contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "language,mode,expected",
    [
        ("fr-FR", "pipeline", "fr"),
        ("en_GB", "pipeline", "en"),
        ("DE", "pipeline", "de"),
        (None, "pipeline", None),
        ("fr", "auto", None),
    ],
)
def test_normalize_language(language, mode, expected):
    assert normalize_language(language, mode) == expected


def test_pcm_to_wav_round_trip():
    assert _wav_frames(pcm_to_wav(CHUNK * 2)) == CHUNK * 2


def test_entity_audio_contract():
    provider = _make_provider()
    assert provider.supported_languages == STT_SUPPORTED_LANGUAGES
    assert provider.supported_formats == [stt.AudioFormats.WAV]
    assert provider.supported_codecs == [stt.AudioCodecs.PCM]
    assert provider.supported_bit_rates == [stt.AudioBitRates.BITRATE_16]
    assert provider.supported_sample_rates == [stt.AudioSampleRates.SAMPLERATE_16000]
    assert provider.supported_channels == [stt.AudioChannels.CHANNEL_MONO]
