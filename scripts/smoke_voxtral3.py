#!/usr/bin/env python
"""Manual smoke test of the Voxtral 3 stack used by HomeStral.

Needs ``MISTRAL_API_KEY`` in the environment and the dev venv (``scripts/setup``).
Never run in CI: it calls the paid Mistral API (a few cents per run).

Steps, each reported on stdout with timings:

1. ``models.list()``: which Voxtral / Mistral chat ids the key can use.
2. Voxtral TTS 3: one sentence as WAV (checks the base64 payload) and the same
   sentence streamed as PCM (time to first audio chunk).
3. The TTS output resampled to 16 kHz mono PCM, i.e. the audio format Home
   Assistant hands to STT entities.
4. Voxtral Mini Transcribe 3 (batch) with ``language="fr"`` and a multi-word
   ``context_bias``.
5. Voxtral Mini Transcribe Realtime 3 over websocket with turn detection:
   every event is printed with its elapsed time (session settings are sent
   before the first audio chunk, chunks are paced like a live microphone).
6. Conversations API streaming with a function tool: event types in order,
   to settle whether ``function.call.delta`` arrives once or incrementally.

Usage::

    MISTRAL_API_KEY=... .venv/bin/python scripts/smoke_voxtral3.py [--out DIR] [--audio file.wav]

``--audio`` transcribes your own 16 kHz / 16-bit / mono WAV instead of the
synthesized sentence.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import re
import sys
import time
import wave
from pathlib import Path

import audioop

SENTENCE = "Allume la lumière du salon et ferme le volet roulant de la cuisine."
CONTEXT_BIAS = ["volet roulant", "lumière du salon", "cuisine", "Homestral", "Home Assistant"]
EXPECTED_MODELS = [
    "voxtral-mini-transcribe-3-0",
    "voxtral-mini-transcribe-realtime-3-0",
    "voxtral-small-transcribe-3-0",
    "voxtral-mini-tts-3-0",
    "mistral-small-latest",
    "mistral-large-latest",
]
PROBE_MODELS = ["voxtral-mini-latest", "voxtral-mini-tts-latest", "mistral-large-4", "mistral-large-4-0"]
TTS_MODEL = "voxtral-mini-tts-3-0"
TTS_VOICE = "voice_592"  # Marie (fr)
STT_BATCH_MODEL = "voxtral-mini-transcribe-3-0"
STT_REALTIME_MODEL = "voxtral-mini-transcribe-realtime-3-0"
CHAT_MODEL = "mistral-small-latest"
REALTIME_URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime"
SAMPLE_RATE = 16000
CHUNK_MS = 100


def banner(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def read_wav(data: bytes) -> tuple[bytes, int, int, int]:
    with wave.open(io.BytesIO(data), "rb") as wav:
        return wav.readframes(wav.getnframes()), wav.getframerate(), wav.getsampwidth(), wav.getnchannels()


def to_16k_mono(pcm: bytes, rate: int, width: int, channels: int) -> bytes:
    if channels == 2:
        pcm = audioop.tomono(pcm, width, 0.5, 0.5)
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if rate != SAMPLE_RATE:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, SAMPLE_RATE, None)
    return pcm


async def step_models(client) -> None:
    banner("1. models.list()")
    response = await client.models.list_async()
    ids = sorted({m.id for m in response.data})
    pattern = re.compile(r"voxtral|mistral-(small|large|medium)|ministral", re.I)
    for model_id in ids:
        if pattern.search(model_id):
            print(f"  {model_id}")
    for expected in EXPECTED_MODELS:
        print(f"  expected {expected}: {'present' if expected in ids else 'MISSING'}")
    for probe in PROBE_MODELS:
        print(f"  probe    {probe}: {'present' if probe in ids else 'absent'}")


async def step_tts(client, out: Path) -> bytes:
    banner("2. Voxtral TTS 3")
    started = time.perf_counter()
    response = await client.audio.speech.complete_async(
        model=TTS_MODEL, input=SENTENCE, voice_id=TTS_VOICE, response_format="wav"
    )
    elapsed = time.perf_counter() - started
    payload = response.audio_data
    print(f"  audio_data type: {type(payload).__name__}, length {len(payload)}")
    audio = base64.b64decode(payload) if isinstance(payload, str) else bytes(payload)
    print(f"  decoded {len(audio)} bytes in {elapsed:.2f}s, RIFF header: {audio[:4] == b'RIFF'}")
    _pcm, rate, width, channels = read_wav(audio)
    print(f"  wav: {rate} Hz, {width * 8}-bit, {channels} channel(s)")
    (out / "tts.wav").write_bytes(audio)

    started = time.perf_counter()
    first_chunk = None
    chunks: list[bytes] = []
    async with await client.audio.speech.complete_async(
        model=TTS_MODEL, input=SENTENCE, voice_id=TTS_VOICE, response_format="pcm", stream=True
    ) as stream:
        async for event in stream:
            if event.event == "speech.audio.delta":
                if first_chunk is None:
                    first_chunk = time.perf_counter() - started
                chunks.append(base64.b64decode(event.data.audio_data))
            elif event.event == "speech.audio.done":
                print(f"  stream usage: {event.data.usage}")
    total = time.perf_counter() - started
    pcm = b"".join(chunks)
    print(
        f"  pcm stream: {len(chunks)} chunks, {len(pcm)} bytes, first audio after {first_chunk:.2f}s, total {total:.2f}s"
    )
    (out / "tts_stream.wav").write_bytes(wav_bytes(pcm, 24000))
    return audio


def step_resample(audio_wav: bytes, out: Path) -> bytes:
    banner("3. resample to 16 kHz mono PCM (Home Assistant STT format)")
    pcm, rate, width, channels = read_wav(audio_wav)
    pcm16k = to_16k_mono(pcm, rate, width, channels)
    print(f"  {rate} Hz -> {SAMPLE_RATE} Hz: {len(pcm16k)} bytes = {len(pcm16k) / (SAMPLE_RATE * 2):.2f}s")
    (out / "sample_16k.wav").write_bytes(wav_bytes(pcm16k, SAMPLE_RATE))
    return pcm16k


async def step_batch_stt(client, pcm16k: bytes) -> None:
    banner("4. Voxtral Mini Transcribe 3 (batch)")
    from mistralai.client.models import File

    started = time.perf_counter()
    response = await client.audio.transcriptions.complete_async(
        model=STT_BATCH_MODEL,
        file=File(file_name="sample.wav", content=wav_bytes(pcm16k, SAMPLE_RATE), content_type="audio/wav"),
        language="fr",
        context_bias=CONTEXT_BIAS,
    )
    print(f"  {time.perf_counter() - started:.2f}s, language={getattr(response, 'language', '?')!r}")
    print(f"  text: {response.text!r}")
    print(f"  expected: {SENTENCE!r}")


async def step_realtime_stt(api_key: str, pcm16k: bytes) -> None:
    banner("5. Voxtral Mini Transcribe Realtime 3 (websocket, turn detection)")
    from mistralai.client.models import (
        AudioFormat,
        RealtimeTranscriptionInputAudioAppend,
        RealtimeTranscriptionInputAudioEnd,
        RealtimeTranscriptionSessionUpdateMessage,
        RealtimeTranscriptionSessionUpdatePayload,
        TurnDetectionConfig,
    )
    from websockets.asyncio.client import connect

    url = f"{REALTIME_URL}?model={STT_REALTIME_MODEL}"
    started = time.perf_counter()
    chunk_bytes = SAMPLE_RATE * 2 * CHUNK_MS // 1000
    text_parts: list[str] = []
    last_audio_at: float | None = None

    async with connect(url, additional_headers={"Authorization": f"Bearer {api_key}"}) as ws:
        created = json.loads(await ws.recv())
        print(
            f"  {time.perf_counter() - started:6.2f}s {created.get('type')} (defaults: {json.dumps(created.get('session'))[:160]})"
        )

        update = RealtimeTranscriptionSessionUpdateMessage(
            session=RealtimeTranscriptionSessionUpdatePayload(
                audio_format=AudioFormat(encoding="pcm_s16le", sample_rate=SAMPLE_RATE),
                target_streaming_delay_ms=480,
                language="fr",
                context_bias=CONTEXT_BIAS,
                turn_detection=TurnDetectionConfig(),
            )
        )
        await ws.send(update.model_dump_json(exclude_unset=True))

        async def send_audio() -> None:
            nonlocal last_audio_at
            for offset in range(0, len(pcm16k), chunk_bytes):
                chunk = pcm16k[offset : offset + chunk_bytes]
                await ws.send(
                    RealtimeTranscriptionInputAudioAppend(audio=base64.b64encode(chunk).decode()).model_dump_json()
                )
                await asyncio.sleep(CHUNK_MS / 1000)
            # one second of silence so turn detection can fire before input_audio.end
            silence = b"\x00" * chunk_bytes
            for _ in range(10):
                await ws.send(
                    RealtimeTranscriptionInputAudioAppend(audio=base64.b64encode(silence).decode()).model_dump_json()
                )
                await asyncio.sleep(CHUNK_MS / 1000)
            last_audio_at = time.perf_counter()
            await ws.send(RealtimeTranscriptionInputAudioEnd().model_dump_json())

        sender = asyncio.create_task(send_audio())
        try:
            async for raw in ws:
                event = json.loads(raw)
                elapsed = time.perf_counter() - started
                event_type = event.get("type")
                if event_type == "transcription.text.delta":
                    text_parts.append(event.get("text", ""))
                    print(f"  {elapsed:6.2f}s delta {event.get('text')!r}")
                elif event_type == "transcription.done":
                    since_audio = (
                        f", {elapsed - (last_audio_at - started):.2f}s after input_audio.end" if last_audio_at else ""
                    )
                    print(
                        f"  {elapsed:6.2f}s done{since_audio}: {event.get('text')!r} (language={event.get('language')!r})"
                    )
                    break
                elif event_type == "error":
                    print(f"  {elapsed:6.2f}s ERROR {event.get('error')}")
                    break
                else:
                    extra = {k: v for k, v in event.items() if k not in {"type", "session"}}
                    print(f"  {elapsed:6.2f}s {event_type} {extra if extra else ''}")
        finally:
            sender.cancel()
    print(f"  deltas joined: {''.join(text_parts)!r}")


async def step_conversation_stream(client) -> None:
    banner("6. Conversations API streaming with a function tool")
    from mistralai.client.models import Function, FunctionTool

    tool = FunctionTool(
        function=Function(
            name="get_ha_weather",
            description="Météo locale depuis Home Assistant",
            parameters={"type": "object", "properties": {}, "required": []},
        )
    )
    started = time.perf_counter()
    event_types: list[str] = []
    function_events: list[dict] = []
    stream = await client.beta.conversations.start_stream_async(
        model=CHAT_MODEL,
        inputs="Quel temps fait-il à la maison ? Utilise l'outil get_ha_weather.",
        instructions="Tu es un assistant domotique. Utilise les outils disponibles.",
        tools=[tool],
    )
    async with stream as events:
        async for event in events:
            data = getattr(event, "data", event)
            event_type = getattr(data, "type", type(data).__name__)
            event_types.append(event_type)
            if event_type == "function.call.delta":
                function_events.append(
                    {
                        "output_index": getattr(data, "output_index", None),
                        "name": data.name,
                        "arguments": data.arguments,
                    }
                )
            elif event_type == "message.output.delta":
                content = getattr(data, "content", "")
                print(f"  {time.perf_counter() - started:6.2f}s text {content!r}")
            elif event_type in {"conversation.response.done", "conversation.response.error"}:
                print(f"  {time.perf_counter() - started:6.2f}s {event_type}")
                break
    print(f"  event types: {event_types}")
    print(f"  function.call.delta events: {len(function_events)} -> {function_events}")
    if len(function_events) == 1:
        print("  => function calls arrive once with complete arguments")
    elif function_events:
        print("  => function call arguments arrive incrementally, accumulate per output_index")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("smoke_out"), help="directory for the generated audio files")
    parser.add_argument("--audio", type=Path, help="your own 16 kHz / 16-bit / mono WAV to transcribe")
    args = parser.parse_args()

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print("MISTRAL_API_KEY is not set", file=sys.stderr)
        return 2

    from mistralai.client import Mistral

    args.out.mkdir(parents=True, exist_ok=True)
    client = Mistral(api_key=api_key)
    failures = 0

    async def run(step, *step_args):
        nonlocal failures
        try:
            return await step(*step_args)
        except Exception as exc:  # report and continue with the next step
            failures += 1
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            return None

    await run(step_models, client)
    if args.audio:
        pcm, rate, width, channels = read_wav(args.audio.read_bytes())
        pcm16k = to_16k_mono(pcm, rate, width, channels)
        print(f"\nusing {args.audio}: {len(pcm16k) / (SAMPLE_RATE * 2):.2f}s of audio")
        await run(step_tts, client, args.out)
    else:
        audio_wav = await run(step_tts, client, args.out)
        pcm16k = step_resample(audio_wav, args.out) if audio_wav else None
    if pcm16k:
        await run(step_batch_stt, client, pcm16k)
        await run(step_realtime_stt, api_key, pcm16k)
    await run(step_conversation_stream, client)

    banner("summary")
    print(f"  {failures} failed step(s); audio files in {args.out.resolve()}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
