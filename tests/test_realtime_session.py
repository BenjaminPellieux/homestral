"""Tests for the Voxtral 3 realtime transcription session.

A fake websocket server (``websockets.asyncio.server``) plays the documented
protocol on 127.0.0.1, so the session is exercised end to end without the
Mistral API: settings before audio, base64 chunks, turn events, early end,
errors and timeouts.
"""

import asyncio
import base64
import json
from contextlib import asynccontextmanager

import pytest
from mistralai.client.models import (
    RealtimeTranscriptionError,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
    TurnDetectionConfig,
    TurnDetectionEagerEndEvent,
    TurnDetectionEndEvent,
    TurnDetectionStartEvent,
)
from mistralai.extra.realtime.connection import UnknownRealtimeEvent
from websockets.asyncio.server import serve

from custom_components.homestral.voxtral_realtime import (
    STREAMING_DELAYS,
    TURN_PRESETS,
    RealtimeSession,
    RealtimeSessionError,
    parse_event,
    turn_detection_preset,
    validate_turn_detection,
)

MODEL = "voxtral-mini-transcribe-realtime-3-0"
DEFAULT_SESSION = {
    "request_id": "req_1",
    "model": MODEL,
    "audio_format": {"encoding": "pcm_s16le", "sample_rate": 16000},
    "target_streaming_delay_ms": 480,
}
CHUNKS = [b"\x01\x02" * 800, b"\x03\x04" * 800, b"\x05\x06" * 800]


def delta(text):
    return {"type": "transcription.text.delta", "text": text}


def done(text):
    return {
        "type": "transcription.done",
        "text": text,
        "language": "fr",
        "model": MODEL,
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class FakeRealtimeServer:
    """Scripted server: events sent after the n-th audio chunk and after input_audio.end."""

    def __init__(self, *, on_chunk=None, on_end=None, silent=False, reject_settings=False):
        self.received: list[dict] = []
        self.on_chunk = on_chunk or {}
        self.on_end = list(on_end or [])
        self.silent = silent
        self.reject_settings = reject_settings
        self.path = None
        self.headers = None

    async def handler(self, ws):
        self.path = ws.request.path
        self.headers = ws.request.headers
        if self.silent:
            await asyncio.sleep(1)  # longer than the client's connect_timeout, short for the suite
            return
        await ws.send(json.dumps({"type": "session.created", "session": DEFAULT_SESSION}))
        update = json.loads(await ws.recv())
        self.received.append(update)
        if self.reject_settings:
            await ws.send(
                json.dumps({"type": "error", "error": {"message": "Invalid language alpha2 code", "code": 400}})
            )
            return
        await ws.send(
            json.dumps({"type": "session.updated", "session": {**DEFAULT_SESSION, **update.get("session", {})}})
        )
        chunks = 0
        async for raw in ws:
            message = json.loads(raw)
            self.received.append(message)
            if message["type"] == "input_audio.append":
                chunks += 1
                for event in self.on_chunk.get(chunks, []):
                    await ws.send(json.dumps(event))
            elif message["type"] == "input_audio.end":
                for event in self.on_end:
                    await ws.send(json.dumps(event))
                return

    @property
    def types(self):
        return [message["type"] for message in self.received]

    @property
    def settings(self):
        return self.received[0]["session"]

    @property
    def audio(self):
        return b"".join(base64.b64decode(m["audio"]) for m in self.received if m["type"] == "input_audio.append")


@asynccontextmanager
async def running(server, **serve_kwargs):
    async with serve(server.handler, "127.0.0.1", 0, **serve_kwargs) as ws_server:
        port = next(iter(ws_server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}/v1/audio/transcriptions/realtime"


async def collect(session, chunks, *, end_on=None):
    """Send chunks (then input_audio.end) and collect events until transcription.done."""

    async def send():
        for chunk in chunks:
            await session.send_audio(chunk)
        if end_on is None:
            await session.end_audio()

    sender = asyncio.create_task(send())
    events = []
    async for event in session.events():
        events.append(event)
        if end_on is not None and isinstance(event, end_on):
            await session.end_audio()
        if isinstance(event, TranscriptionStreamDone | RealtimeTranscriptionError):
            break
    await sender
    return events


@pytest.mark.asyncio
async def test_settings_are_sent_before_any_audio_and_events_are_parsed():
    server = FakeRealtimeServer(on_end=[delta("Allume"), delta(" la lumière"), done("Allume la lumière")])
    async with running(server) as url:
        session = RealtimeSession(
            "sk-test",
            language="fr",
            context_bias=["volet roulant", "Salon"],
            turn_detection=turn_detection_preset("aggressive"),
            streaming_delay_ms=960,
            url=url,
        )
        async with session:
            assert session.is_open
            assert session.session["request_id"] == "req_1"
            events = await collect(session, CHUNKS)
        assert not session.is_open

    assert [type(e) for e in events] == [
        TranscriptionStreamTextDelta,
        TranscriptionStreamTextDelta,
        TranscriptionStreamDone,
    ]
    assert events[-1].text == "Allume la lumière"
    assert server.types == [
        "session.update",
        "input_audio.append",
        "input_audio.append",
        "input_audio.append",
        "input_audio.end",
    ]
    assert server.settings == {
        "audio_format": {"encoding": "pcm_s16le", "sample_rate": 16000},
        "target_streaming_delay_ms": 960,
        "language": "fr",
        "context_bias": ["volet roulant", "Salon"],
        "turn_detection": TURN_PRESETS["aggressive"],
    }
    assert server.audio == b"".join(CHUNKS)
    assert f"model={MODEL}" in server.path
    assert server.headers["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_settings_message_omits_unset_fields():
    message = json.loads(RealtimeSession("k", url="ws://x").settings_message())
    assert message["session"] == {
        "audio_format": {"encoding": "pcm_s16le", "sample_rate": 16000},
        "target_streaming_delay_ms": 480,
    }


@pytest.mark.asyncio
async def test_turn_end_is_parsed_and_audio_can_be_ended_early():
    server = FakeRealtimeServer(
        on_chunk={
            2: [{"type": "turn.start", "time_s": 0.1}, {"type": "turn.end", "time_s": 1.0, "end_reason": "threshold"}]
        },
        on_end=[done("ok")],
    )
    async with running(server) as url:
        async with RealtimeSession("k", url=url) as session:
            events = await collect(session, CHUNKS[:2], end_on=TurnDetectionEndEvent)

    assert [type(e) for e in events] == [TurnDetectionStartEvent, TurnDetectionEndEvent, TranscriptionStreamDone]
    assert events[1].end_reason == "threshold"
    assert server.types[-1] == "input_audio.end"
    assert server.types.count("input_audio.append") == 2


@pytest.mark.asyncio
async def test_eager_end_and_unknown_events_are_yielded():
    server = FakeRealtimeServer(
        on_chunk={1: [{"type": "turn.eager_end", "time_s": 0.8}, {"type": "something.new", "foo": 1}]},
        on_end=[done("ok")],
    )
    async with running(server) as url:
        async with RealtimeSession("k", url=url) as session:
            events = await collect(session, CHUNKS[:1])

    assert isinstance(events[0], TurnDetectionEagerEndEvent)
    assert events[0].time_s == 0.8
    assert isinstance(events[1], UnknownRealtimeEvent)
    assert events[1].type == "something.new"


@pytest.mark.asyncio
async def test_error_event_is_yielded():
    server = FakeRealtimeServer(on_chunk={1: [{"type": "error", "error": {"message": "boom", "code": 500}}]})
    async with running(server) as url:
        async with RealtimeSession("k", url=url) as session:
            events = await collect(session, CHUNKS[:1])

    assert isinstance(events[-1], RealtimeTranscriptionError)
    assert events[-1].error.code == 500


@pytest.mark.asyncio
async def test_rejected_settings_raise_on_connect():
    server = FakeRealtimeServer(reject_settings=True)
    async with running(server) as url:
        session = RealtimeSession("k", language="xx", url=url)
        with pytest.raises(RealtimeSessionError, match="Invalid language"):
            async with session:
                pass
    assert not session.is_open


@pytest.mark.asyncio
async def test_connect_timeout_raises():
    server = FakeRealtimeServer(silent=True)
    async with running(server) as url:
        with pytest.raises(RealtimeSessionError):
            async with RealtimeSession("k", url=url, connect_timeout=0.3):
                pass


@pytest.mark.asyncio
async def test_rejected_handshake_raises():
    server = FakeRealtimeServer()

    def reject(connection, request):
        return connection.respond(401, "Unauthorized")

    async with running(server, process_request=reject) as url:
        with pytest.raises(RealtimeSessionError):
            async with RealtimeSession("bad-key", url=url, connect_timeout=1.0):
                pass


@pytest.mark.asyncio
async def test_send_audio_needs_a_connection_and_end_audio_is_idempotent():
    server = FakeRealtimeServer(on_end=[done("")])
    session = RealtimeSession("k", url="ws://127.0.0.1:1")
    with pytest.raises(RuntimeError):
        await session.send_audio(CHUNKS[0])

    async with running(server) as url:
        async with RealtimeSession("k", url=url) as session:
            await session.send_audio(b"")  # empty chunks are skipped
            await session.send_audio(CHUNKS[0])
            await session.end_audio()
            await session.end_audio()
            with pytest.raises(RuntimeError):
                await session.send_audio(CHUNKS[1])
            async for _event in session.events():
                break
    assert server.types == ["session.update", "input_audio.append", "input_audio.end"]


def test_constructor_and_preset_validation():
    assert {80, 1200, 2400} <= STREAMING_DELAYS
    assert 1201 not in STREAMING_DELAYS
    with pytest.raises(ValueError):
        RealtimeSession("k", streaming_delay_ms=3000)
    with pytest.raises(ValueError):
        RealtimeSession("k", sample_rate=0)
    RealtimeSession("k", streaming_delay_ms=2400)

    assert turn_detection_preset("off") is None
    assert turn_detection_preset(None) is None
    assert turn_detection_preset("default").model_dump(exclude_unset=True) == TURN_PRESETS["default"]
    with pytest.raises(ValueError):
        turn_detection_preset("wild")
    with pytest.raises(ValueError, match="eager_end_threshold"):
        validate_turn_detection(TurnDetectionConfig(eager_end_threshold=0.2, end_threshold=0.33))
    with pytest.raises(ValueError, match="end_timeout_ms"):
        validate_turn_detection(TurnDetectionConfig(min_silence_ms=1000, end_timeout_ms=500))
    with pytest.raises(ValueError):
        RealtimeSession("k", turn_detection=TurnDetectionConfig(eager_end_threshold=0.9))


def test_parse_event_models():
    assert isinstance(parse_event({"type": "turn.eager_end", "time_s": 2.0}), TurnDetectionEagerEndEvent)
    assert isinstance(parse_event({"type": "transcription.text.delta", "text": "a"}), TranscriptionStreamTextDelta)
    broken = parse_event({"type": "turn.end"})
    assert isinstance(broken, UnknownRealtimeEvent)
    assert broken.type == "turn.end" and broken.error
    assert isinstance(parse_event("not a dict"), UnknownRealtimeEvent)
