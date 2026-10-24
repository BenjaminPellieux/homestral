"""Tests for the Voxtral TTS 3 entity.

Two paths are covered:

* streaming (``async_stream_tts_audio``): sentence batching while the answer is
  still being written, one WAV header followed by raw PCM, delivery tags on the
  first batch only, truncation when the API fails mid-stream.
* one-shot (``async_get_tts_audio``): a single request, base64 payload decoded
  before the bytes reach Home Assistant.
"""

import base64
import io
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.components import tts
from homeassistant.exceptions import HomeAssistantError

from custom_components.homestral.const import (
    CONF_TTS_DEFAULT_EMOTION,
    CONF_TTS_DEFAULT_PACE,
    CONF_TTS_EXPRESSIVENESS,
    CONF_TTS_VOICE,
    DEFAULT_TTS_FORMAT,
    DEFAULT_TTS_MODEL,
    TTS_OPTION_EMOTION,
    TTS_OPTION_PACE,
    TTS_SAMPLE_RATE,
    TTS_VOICES,
)
from custom_components.homestral.tts import (
    VoxtralTtsProvider,
    WavStreamReader,
    decode_audio,
    delivery_tags,
    language_key,
    parse_wav_header,
    streaming_wav_header,
)

WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 24
PCM = b"\x01\x02" * 200


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def wav_container(pcm: bytes, rate: int = TTS_SAMPLE_RATE, width: int = 2, channels: int = 1) -> bytes:
    """A streaming WAV container shaped like Mistral's: header then samples."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _delta(pcm: bytes):
    """One SSE audio chunk, as the SDK exposes it (event name + base64 payload)."""
    return SimpleNamespace(event="speech.audio.delta", data=SimpleNamespace(audio_data=base64.b64encode(pcm).decode()))


def _wav_deltas(pcm: bytes = PCM, **fmt):
    """The deltas of one batch: a complete WAV container split in two."""
    blob = wav_container(pcm, **fmt)
    return [_delta(blob[:30]), _delta(blob[30:]), _done()]


def _done():
    return SimpleNamespace(event="speech.audio.done", data=SimpleNamespace(usage={"characters": 10}))


class FakeStream:
    """Async context manager yielding scripted SSE events, like speech.complete(stream=True)."""

    def __init__(self, events, fail_after=None):
        self._events = events
        self._fail_after = fail_after

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for index, event in enumerate(self._events):
            if self._fail_after is not None and index == self._fail_after:
                raise RuntimeError("stream broke")
            yield event


def _make_provider(options=None, stream_script=None, audio_data=None, side_effect=None):
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.data = {"api_key": "k"}
    entry.options = options or {}
    entry.runtime_data = SimpleNamespace(client=MagicMock(), runner=MagicMock(), cache={})
    provider = VoxtralTtsProvider(hass, entry)

    calls: list[dict] = []

    async def complete_async(**kwargs):
        calls.append(kwargs)
        if side_effect is not None:
            raise side_effect
        if kwargs.get("stream"):
            script = stream_script or [_wav_deltas()]
            events = script[min(len(calls) - 1, len(script) - 1)]
            return FakeStream(events) if not isinstance(events, FakeStream) else events
        payload = audio_data if audio_data is not None else base64.b64encode(WAV_BYTES).decode()
        return SimpleNamespace(audio_data=payload)

    provider._client.audio.speech.complete_async = complete_async
    provider.calls = calls
    return provider


async def _message_gen(*chunks):
    for chunk in chunks:
        yield chunk


def _request(provider, *chunks, language="fr", options=None):
    return tts.TTSAudioRequest(language=language, options=options or {}, message_gen=_message_gen(*chunks))


async def _collect(response: tts.TTSAudioResponse) -> bytes:
    return b"".join([chunk async for chunk in response.data_gen])


def _split_header(audio: bytes) -> tuple[bytes, bytes]:
    """Return (header, pcm) and assert the header is a valid streaming WAV header."""
    header_len = len(streaming_wav_header())
    header, body = audio[:header_len], audio[header_len:]
    with wave.open(io.BytesIO(header), "rb") as wav:
        assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (TTS_SAMPLE_RATE, 2, 1)
        assert wav.getnframes() == 0  # streaming: length unknown up front
    assert b"RIFF" not in body, "the header must be emitted exactly once"
    return header, body


# ---------------------------------------------------------------------------
# Streaming path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_emits_one_header_then_pcm_and_uses_voxtral3_defaults():
    provider = _make_provider()

    response = await provider.async_stream_tts_audio(_request(provider, "Bonjour.", " Ça va ?"))
    audio = await _collect(response)

    assert response.extension == DEFAULT_TTS_FORMAT
    _header, body = _split_header(audio)
    # Every batch contributes only its samples: the containers' own headers are stripped.
    assert body == PCM * len(provider.calls)
    first = provider.calls[0]
    assert first["model"] == DEFAULT_TTS_MODEL
    assert first["response_format"] == "wav"  # self-describing, see const.TTS_STREAM_FORMAT
    assert first["stream"] is True
    assert first["voice_id"] == TTS_VOICES["fr"][0][0]


@pytest.mark.asyncio
async def test_stream_supports_streaming_input_is_advertised():
    provider = _make_provider()

    assert provider.async_supports_streaming_input() is True


@pytest.mark.asyncio
async def test_stream_batches_first_sentence_then_three_then_rest():
    """The schedule keeps the first words early: 1 sentence, then 3, then everything."""
    provider = _make_provider()
    sentences = [f"Phrase {i}." for i in range(1, 8)]

    # Chunks deliberately cut across sentence boundaries, as the model streams them.
    chunks = ["Phrase 1. Phra", "se 2. Phrase 3.", " Phrase 4. Phrase 5.", " Phrase 6. Phrase 7."]
    response = await provider.async_stream_tts_audio(_request(provider, *chunks))
    await _collect(response)

    batches = [call["input"] for call in provider.calls]
    assert batches[0] == "Phrase 1."
    assert batches[1] == "Phrase 2. Phrase 3. Phrase 4."
    assert " ".join(batches) == " ".join(sentences)


@pytest.mark.asyncio
async def test_stream_applies_tags_to_the_first_batch_only():
    provider = _make_provider()

    request = _request(
        provider,
        "Première. Deuxième. Troisième. Quatrième. Cinquième.",
        options={TTS_OPTION_EMOTION: "urgent", TTS_OPTION_PACE: "fast"},
    )
    await _collect(await provider.async_stream_tts_audio(request))

    assert provider.calls[0]["input"].startswith("[emotion=urgent][pace=fast]Première.")
    assert all("[emotion=" not in call["input"] for call in provider.calls[1:])


@pytest.mark.asyncio
async def test_stream_entry_defaults_and_expressiveness_are_sent():
    provider = _make_provider(
        {
            CONF_TTS_VOICE: "voice_3137",
            CONF_TTS_DEFAULT_EMOTION: "calm",
            CONF_TTS_DEFAULT_PACE: "slow",
            CONF_TTS_EXPRESSIVENESS: 2.5,
        }
    )

    await _collect(await provider.async_stream_tts_audio(_request(provider, "Bonjour.")))

    call = provider.calls[0]
    assert call["voice_id"] == "voice_3137"
    assert call["expressiveness"] == 2.5
    assert call["input"].startswith("[emotion=calm][pace=slow]")


@pytest.mark.asyncio
async def test_stream_unknown_tag_values_are_dropped():
    provider = _make_provider()

    request = _request(provider, "Bonjour.", options={TTS_OPTION_EMOTION: "ecstatic", TTS_OPTION_PACE: "turbo"})
    await _collect(await provider.async_stream_tts_audio(request))

    assert provider.calls[0]["input"] == "Bonjour."


@pytest.mark.asyncio
async def test_stream_failure_before_any_audio_raises():
    provider = _make_provider(side_effect=RuntimeError("API down"))

    response = await provider.async_stream_tts_audio(_request(provider, "Bonjour."))
    with pytest.raises(HomeAssistantError, match="Voxtral TTS failed"):
        await _collect(response)


@pytest.mark.asyncio
async def test_stream_failure_after_first_chunk_truncates_instead_of_raising():
    """Audio is already playing: the answer is cut short, the player is not broken."""
    provider = _make_provider(stream_script=[[_delta(PCM), _done()], FakeStream([_delta(PCM)], fail_after=0)])

    response = await provider.async_stream_tts_audio(
        _request(provider, "Une. Deux. Trois. Quatre. Cinq. Six. Sept. Huit.")
    )
    audio = await _collect(response)

    _header, body = _split_header(audio)
    assert body == PCM  # only the first batch made it


@pytest.mark.asyncio
async def test_stream_without_audio_still_returns_a_valid_wav():
    provider = _make_provider(stream_script=[[_done()]])

    audio = await _collect(await provider.async_stream_tts_audio(_request(provider, "Bonjour.")))

    assert audio == streaming_wav_header()


@pytest.mark.asyncio
async def test_stream_empty_message_makes_no_request():
    provider = _make_provider()

    audio = await _collect(await provider.async_stream_tts_audio(_request(provider, "", "   ")))

    assert provider.calls == []
    assert audio == streaming_wav_header()


# ---------------------------------------------------------------------------
# One-shot path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tts_audio_decodes_base64_and_uses_voxtral3_defaults():
    provider = _make_provider()

    extension, audio = await provider.async_get_tts_audio("Bonjour", "fr", {})

    assert extension == DEFAULT_TTS_FORMAT
    assert audio == WAV_BYTES
    call = provider.calls[0]
    assert call["model"] == DEFAULT_TTS_MODEL
    assert call["input"] == "Bonjour"
    assert call["response_format"] == DEFAULT_TTS_FORMAT
    assert call["voice_id"] == TTS_VOICES["fr"][0][0]
    assert "stream" not in call


@pytest.mark.asyncio
async def test_get_tts_audio_picks_voice_by_language_and_honours_the_option():
    provider = _make_provider()

    await provider.async_get_tts_audio("Hello", "en-GB", None)
    assert provider.calls[-1]["voice_id"] == TTS_VOICES["en"][0][0]

    await provider.async_get_tts_audio("Bonjour", "fr", {tts.ATTR_VOICE: "voice_3137"})
    assert provider.calls[-1]["voice_id"] == "voice_3137"

    await provider.async_get_tts_audio("Hej", "sv", {})
    assert provider.calls[-1]["voice_id"] == TTS_VOICES["fr"][0][0]


@pytest.mark.asyncio
async def test_get_tts_audio_prefixes_tags():
    provider = _make_provider({CONF_TTS_DEFAULT_EMOTION: "warm"})

    await provider.async_get_tts_audio("Bonjour", "fr", {TTS_OPTION_PACE: "slow"})

    assert provider.calls[0]["input"] == "[emotion=warm][pace=slow]Bonjour"


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


# ---------------------------------------------------------------------------
# Entity contract and helpers
# ---------------------------------------------------------------------------


def test_supported_voices_per_language():
    provider = _make_provider()

    voices = provider.async_get_supported_voices("fr-FR")

    assert voices is not None
    assert [v.voice_id for v in voices] == [voice_id for voice_id, _name in TTS_VOICES["fr"]]
    assert all(isinstance(v, tts.Voice) for v in voices)
    assert provider.async_get_supported_voices("sv") is None


def test_entity_declares_options_and_languages():
    provider = _make_provider()

    assert provider.supported_options == [tts.ATTR_VOICE, TTS_OPTION_EMOTION, TTS_OPTION_PACE]
    assert provider.default_language == "fr"
    assert set(provider.supported_languages) == set(TTS_VOICES)


@pytest.mark.parametrize(
    "language,expected",
    [("fr", "fr"), ("fr-FR", "fr"), ("en_GB", "en"), ("EN-us", "en"), ("sv", None), (None, None), ("", None)],
)
def test_language_key(language, expected):
    assert language_key(language) == expected


@pytest.mark.parametrize(
    "emotion,pace,expected",
    [
        ("happy", "fast", "[emotion=happy][pace=fast]"),
        ("happy", None, "[emotion=happy]"),
        (None, "slow", "[pace=slow]"),
        ("none", "none", ""),
        ("ecstatic", "turbo", ""),
        (None, None, ""),
    ],
)
def test_delivery_tags(emotion, pace, expected):
    assert delivery_tags(emotion, pace) == expected


def test_decode_audio_helpers():
    assert decode_audio(base64.b64encode(b"abc").decode()) == b"abc"
    assert decode_audio(b"abc") == b"abc"


# ---------------------------------------------------------------------------
# Streamed WAV containers
# ---------------------------------------------------------------------------


def test_parse_wav_header_reads_the_real_parameters():
    blob = wav_container(PCM, rate=24000, width=2, channels=1)

    assert parse_wav_header(blob) == ((24000, 2, 1), 44)
    # A truncated buffer asks for more bytes rather than guessing.
    assert parse_wav_header(blob[:20]) is None
    assert parse_wav_header(b"") is None


def test_parse_wav_header_accepts_the_streaming_length_placeholder():
    """Mistral streams RIFF with 0xFFFFFFFF as the length; it must not be read as a size."""
    blob = bytearray(wav_container(PCM))
    blob[4:8] = (0xFFFFFFFF).to_bytes(4, "little")

    assert parse_wav_header(bytes(blob)) == ((24000, 2, 1), 44)


def test_parse_wav_header_rejects_a_non_container():
    with pytest.raises(ValueError, match="RIFF"):
        parse_wav_header(b"\x00\x01" * 40)


def test_wav_stream_reader_handles_a_header_split_across_chunks():
    blob = wav_container(PCM)
    reader = WavStreamReader()

    out = b"".join(reader.feed(blob[i : i + 7]) for i in range(0, len(blob), 7))

    assert reader.params == (24000, 2, 1)
    assert out == PCM


def test_wav_stream_reader_passes_raw_bytes_through_when_there_is_no_container():
    reader = WavStreamReader()

    out = reader.feed(PCM)

    assert reader.malformed is True
    assert out == PCM


@pytest.mark.asyncio
async def test_stream_header_uses_the_format_the_api_declares():
    """A 48 kHz answer must be announced as 48 kHz, not as the hardcoded default."""
    provider = _make_provider(stream_script=[_wav_deltas(PCM, rate=48000, width=2, channels=1)])

    audio = await _collect(await provider.async_stream_tts_audio(_request(provider, "Bonjour.")))

    with wave.open(io.BytesIO(audio[:44]), "rb") as w:
        assert w.getframerate() == 48000
        assert w.getnframes() == 0  # streaming: the length stays unknown
    assert audio[44:] == PCM


@pytest.mark.asyncio
async def test_stream_strips_the_header_of_every_later_batch():
    provider = _make_provider(stream_script=[_wav_deltas(PCM), _wav_deltas(PCM)])

    audio = await _collect(
        await provider.async_stream_tts_audio(_request(provider, "Une phrase. Puis une deuxième phrase."))
    )

    _header, body = _split_header(audio)
    assert body == PCM * 2
    assert b"RIFF" not in body
