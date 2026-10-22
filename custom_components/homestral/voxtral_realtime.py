"""Voxtral 3 realtime transcription session over WebSocket.

HomeStral owns the socket: the SDK's ``RealtimeConnection.update_session()``
only sends ``audio_format`` and ``target_streaming_delay_ms``, while
``language``, ``context_bias`` and ``turn_detection`` must reach the server
before the first audio chunk. Every message is still built and parsed with
the SDK pydantic models, so the wire format stays the documented one.

Protocol (https://docs.mistral.ai/studio/audio/speech-to-text/transcribe-in-realtime)::

    server  session.created
    client  session.update              all settings, before any audio
    server  session.updated
    client  input_audio.append ...      base64 pcm_s16le chunks
    client  input_audio.end
    server  transcription.text.delta ... turn.* ... transcription.done | error
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Iterable
from typing import Any
from urllib.parse import urlencode

from mistralai.client.models import (
    AudioFormat,
    RealtimeTranscriptionError,
    RealtimeTranscriptionInputAudioAppend,
    RealtimeTranscriptionInputAudioEnd,
    RealtimeTranscriptionSessionCreated,
    RealtimeTranscriptionSessionUpdated,
    RealtimeTranscriptionSessionUpdateMessage,
    RealtimeTranscriptionSessionUpdatePayload,
    TranscriptionStreamDone,
    TranscriptionStreamLanguage,
    TranscriptionStreamSegmentDelta,
    TranscriptionStreamTextDelta,
    TurnDetectionConfig,
    TurnDetectionEagerEndEvent,
    TurnDetectionEndEvent,
    TurnDetectionResumeEvent,
    TurnDetectionStartEvent,
)
from mistralai.extra.realtime.connection import UnknownRealtimeEvent, parse_realtime_event
from pydantic import ValidationError
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK, WebSocketException

from .const import STT_MODEL_REALTIME, STT_SAMPLE_RATE
from .logging_config import get_logger

_LOGGER = get_logger(__name__)

REALTIME_URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime"
# target_streaming_delay_ms: 80 to 1200 ms, or 2400 ms; other values are rejected by the API.
STREAMING_DELAYS = frozenset(range(80, 1201)) | {2400}
DEFAULT_STREAMING_DELAY_MS = 480
DEFAULT_CONNECT_TIMEOUT = 5.0

# Documented presets (https://docs.mistral.ai/studio/audio/speech-to-text/turn-detection).
TURN_PRESETS: dict[str, dict[str, float | int]] = {
    "default": {
        "start_threshold": 0.5,
        "eager_end_threshold": 0.5,
        "end_threshold": 0.33,
        "min_silence_ms": 500,
        "end_timeout_ms": 3000,
    },
    "aggressive": {
        "start_threshold": 0.5,
        "eager_end_threshold": 0.4,
        "end_threshold": 0.33,
        "min_silence_ms": 300,
        "end_timeout_ms": 2500,
    },
}

_TURN_EVENT_MODELS = {
    "turn.start": TurnDetectionStartEvent,
    "turn.eager_end": TurnDetectionEagerEndEvent,
    "turn.resume": TurnDetectionResumeEvent,
    "turn.end": TurnDetectionEndEvent,
}

TurnEvent = TurnDetectionStartEvent | TurnDetectionEagerEndEvent | TurnDetectionResumeEvent | TurnDetectionEndEvent
RealtimeEvent = (
    RealtimeTranscriptionSessionCreated
    | RealtimeTranscriptionSessionUpdated
    | RealtimeTranscriptionError
    | TranscriptionStreamLanguage
    | TranscriptionStreamSegmentDelta
    | TranscriptionStreamTextDelta
    | TranscriptionStreamDone
    | TurnEvent
    | UnknownRealtimeEvent
)


class RealtimeSessionError(Exception):
    """Connection or protocol failure of a realtime transcription session."""


def turn_detection_preset(name: str | None) -> TurnDetectionConfig | None:
    """Return the TurnDetectionConfig of a documented preset, or None for "off"."""
    if not name or name == "off":
        return None
    try:
        values = TURN_PRESETS[name]
    except KeyError:
        raise ValueError(f"unknown turn detection preset: {name!r}") from None
    return TurnDetectionConfig(**values)


def validate_turn_detection(config: TurnDetectionConfig) -> None:
    """Enforce the documented constraints; the server rejects the session otherwise."""
    start = config.start_threshold if isinstance(config.start_threshold, float | int) else 0.5
    eager = config.eager_end_threshold if isinstance(config.eager_end_threshold, float | int) else 0.5
    end = config.end_threshold if isinstance(config.end_threshold, float | int) else 0.33
    if not (start >= eager > end):
        raise ValueError(
            f"turn detection needs start_threshold >= eager_end_threshold > end_threshold, got {start}, {eager}, {end}"
        )
    min_silence = config.min_silence_ms if isinstance(config.min_silence_ms, int) else 500
    end_timeout = config.end_timeout_ms if isinstance(config.end_timeout_ms, int) else None
    if end_timeout is not None and end_timeout < min_silence:
        raise ValueError(f"turn detection needs end_timeout_ms >= min_silence_ms, got {end_timeout} < {min_silence}")


def parse_event(data: Any) -> RealtimeEvent:
    """Parse one server message: SDK parser plus the turn.* models it does not know."""
    event_type = data.get("type") if isinstance(data, dict) else None
    model = _TURN_EVENT_MODELS.get(event_type)
    if model is not None:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            return UnknownRealtimeEvent(type=event_type, content=data, error=str(exc))
    return parse_realtime_event(data)


class RealtimeSession:
    """One WebSocket session, i.e. one utterance.

    Usage::

        async with RealtimeSession(api_key, language="fr", context_bias=[...]) as session:
            sender = asyncio.create_task(forward(session))   # send_audio() then end_audio()
            async for event in session.events():
                ...
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = STT_MODEL_REALTIME,
        sample_rate: int = STT_SAMPLE_RATE,
        language: str | None = None,
        context_bias: Iterable[str] = (),
        turn_detection: TurnDetectionConfig | None = None,
        streaming_delay_ms: int = DEFAULT_STREAMING_DELAY_MS,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        url: str = REALTIME_URL,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if streaming_delay_ms not in STREAMING_DELAYS:
            raise ValueError(f"target_streaming_delay_ms must be 80 to 1200 or 2400, got {streaming_delay_ms}")
        if turn_detection is not None:
            validate_turn_detection(turn_detection)
        self._api_key = api_key
        self._model = model
        self._sample_rate = sample_rate
        self._language = language
        self._context_bias = [str(entry) for entry in context_bias if str(entry).strip()]
        self._turn_detection = turn_detection
        self._streaming_delay_ms = streaming_delay_ms
        self._connect_timeout = connect_timeout
        self._url = url
        self._ws: Any = None
        self._configured = False
        self._audio_ended = False
        self.session: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._ws is not None

    @property
    def audio_ended(self) -> bool:
        return self._audio_ended

    async def __aenter__(self) -> RealtimeSession:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def settings_message(self) -> str:
        """The session.update JSON, built with the SDK models (every setting in one message)."""
        payload: dict[str, Any] = {
            "audio_format": AudioFormat(encoding="pcm_s16le", sample_rate=self._sample_rate),
            "target_streaming_delay_ms": self._streaming_delay_ms,
        }
        if self._language:
            payload["language"] = self._language
        if self._context_bias:
            payload["context_bias"] = self._context_bias
        if self._turn_detection is not None:
            payload["turn_detection"] = self._turn_detection
        # ``type`` is set explicitly: exclude_unset would otherwise drop the default literal.
        message = RealtimeTranscriptionSessionUpdateMessage(
            type="session.update", session=RealtimeTranscriptionSessionUpdatePayload(**payload)
        )
        return message.model_dump_json(exclude_unset=True)

    async def connect(self) -> None:
        """Open the socket, wait for session.created, send the settings, wait for session.updated."""
        uri = f"{self._url}?{urlencode({'model': self._model})}"
        try:
            self._ws = await connect(
                uri,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                open_timeout=self._connect_timeout,
            )
            created = await asyncio.wait_for(self._recv_json(), self._connect_timeout)
            if created.get("type") == "error":
                raise RealtimeSessionError(_error_text(created))
            if created.get("type") != "session.created":
                raise RealtimeSessionError(f"expected session.created, got {created.get('type')!r}")
            self.session = dict(created.get("session") or {})

            await self._ws.send(self.settings_message())
            updated = await asyncio.wait_for(self._recv_json(), self._connect_timeout)
            if updated.get("type") == "error":
                raise RealtimeSessionError(_error_text(updated))
            if updated.get("type") != "session.updated":
                raise RealtimeSessionError(f"expected session.updated, got {updated.get('type')!r}")
            self.session = dict(updated.get("session") or self.session)
            self._configured = True
        except RealtimeSessionError:
            await self.close()
            raise
        except (OSError, WebSocketException, TimeoutError, ValueError) as exc:
            await self.close()
            raise RealtimeSessionError(f"realtime connection failed: {exc}") from exc
        _LOGGER.debug(f"[STT realtime] session {self.session.get('request_id')!r} ready: {self.session}")

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is None:
            return
        try:
            await ws.close()
        except Exception:  # closing a broken socket must never raise
            pass

    # ------------------------------------------------------------------
    # Audio in
    # ------------------------------------------------------------------

    async def send_audio(self, pcm: bytes | bytearray | memoryview) -> None:
        """Send one chunk of pcm_s16le audio."""
        if self._ws is None or not self._configured:
            raise RuntimeError("the session is not connected")
        if self._audio_ended:
            raise RuntimeError("audio already ended")
        if not pcm:
            return
        message = RealtimeTranscriptionInputAudioAppend(audio=base64.b64encode(bytes(pcm)).decode("ascii"))
        try:
            await self._ws.send(message.model_dump_json())
        except ConnectionClosed as exc:
            raise RealtimeSessionError(f"connection closed while sending audio: {exc}") from exc

    async def end_audio(self) -> None:
        """Signal the end of the audio; idempotent."""
        if self._audio_ended or self._ws is None:
            self._audio_ended = True
            return
        self._audio_ended = True
        try:
            await self._ws.send(RealtimeTranscriptionInputAudioEnd().model_dump_json())
        except ConnectionClosed:
            pass

    # ------------------------------------------------------------------
    # Events out
    # ------------------------------------------------------------------

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        """Yield parsed server events until the server closes the connection."""
        if self._ws is None:
            raise RuntimeError("the session is not connected")
        try:
            async for raw in self._ws:
                text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes | bytearray) else raw
                try:
                    data = json.loads(text)
                except ValueError as exc:
                    yield UnknownRealtimeEvent(type=None, content=text, error=f"invalid JSON: {exc}")
                    continue
                yield parse_event(data)
        except ConnectionClosedOK:
            return
        except ConnectionClosed as exc:
            raise RealtimeSessionError(f"connection closed: {exc}") from exc

    async def _recv_json(self) -> dict[str, Any]:
        raw = await self._ws.recv()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes | bytearray) else raw
        data = json.loads(text)
        if not isinstance(data, dict):
            raise RealtimeSessionError(f"unexpected server message: {text[:120]!r}")
        return data


def _error_text(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        return f"{error.get('message')} (code {error.get('code')})"
    return str(error)
