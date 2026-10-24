#!/usr/bin/env python
"""Measure what Voxtral TTS actually returns, instead of trusting the documentation.

HomeStral's streaming path asks for ``response_format="pcm"`` and wraps the bytes
in a WAV header it writes itself. Nothing in the Mistral SDK states the sample
rate, the sample width or even whether those bytes are integers or floats, so
that header is a guess. A wrong guess is silent: ffmpeg re-encodes the stream,
exits 0 and plays noise.

This probe settles it. It asks for the same sentence twice:

* as ``wav``, which is self-describing: its header is Mistral's own statement of
  rate, width and channel count;
* as ``pcm`` streamed, the format the integration actually uses.

It then compares the two payloads and reports whether the raw bytes look like
16-bit integers or 32-bit floats, and whether the streamed deltas are
incremental or cumulative.

The key is read from the Home Assistant config entry of the running test
instance (or from MISTRAL_API_KEY) and is never printed.

Usage::

    .venv/bin/python scripts/probe_voxtral_tts.py [--text "..."] [--voice voice_592]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import math
import os
import struct
import subprocess
import sys
import wave

MODEL = "voxtral-mini-tts-3-0"
DEFAULT_TEXT = "Bonjour, la lumière du salon est allumée."
DEFAULT_VOICE = "voice_592"  # Marie, French
CONTAINER = "homestral-dev"
ENTRY_PATH = "/config/.storage/core.config_entries"


# ---------------------------------------------------------------------------
# Key lookup
# ---------------------------------------------------------------------------


def api_key() -> str:
    """Read the key from the environment, else from the test instance. Never printed."""
    if key := os.environ.get("MISTRAL_API_KEY"):
        print("key source: MISTRAL_API_KEY")
        return key

    script = (
        "import json;"
        f"d=json.load(open({ENTRY_PATH!r}));"
        "print(next(e['data']['api_key'] for e in d['data']['entries'] if e['domain']=='homestral'))"
    )
    inner = f"docker exec {CONTAINER} python -c {json.dumps(script)}"
    # Plain docker first; `sg docker` covers a shell session that predates the group.
    for cmd in (["docker", "exec", CONTAINER, "python", "-c", script], ["sg", "docker", "-c", inner]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        lines = [line.strip() for line in out.stdout.splitlines() if line.strip()]
        key = lines[-1] if lines else ""
        # Accept any single opaque token; Mistral keys carry no stable prefix.
        if out.returncode == 0 and len(key) >= 20 and " " not in key:
            print(f"key source: Home Assistant config entry in the {CONTAINER} container")
            return key
    sys.exit("No API key: set MISTRAL_API_KEY or start the homestral-dev container.")


# ---------------------------------------------------------------------------
# Signal statistics
# ---------------------------------------------------------------------------


def as_int16(raw: bytes) -> dict[str, float]:
    """Interpret the bytes as signed 16-bit little-endian and describe the result."""
    n = len(raw) // 2
    if not n:
        return {}
    s = struct.unpack(f"<{n}h", raw[: n * 2])
    peak = max(max(s), -min(s))
    rms = math.sqrt(sum(x * x for x in s) / n)
    near_full = sum(1 for x in s if abs(x) > 30000) / n
    # Real speech moves slowly between neighbouring samples; noise does not.
    jumps = sum(1 for a, b in zip(s, s[1:], strict=False) if abs(a - b) > 20000) / max(n - 1, 1)
    return {"samples": n, "peak": peak, "rms": rms, "near_full": near_full, "big_jumps": jumps}


def as_float32(raw: bytes) -> dict[str, float]:
    """Interpret the bytes as 32-bit floats and describe the result."""
    n = len(raw) // 4
    if not n:
        return {}
    f = struct.unpack(f"<{n}f", raw[: n * 4])
    finite = [x for x in f if -10 < x < 10]
    in_range = sum(1 for x in f if -1.0 <= x <= 1.0) / n
    peak = max((abs(x) for x in finite), default=float("nan"))
    return {"samples": n, "in_minus1_1": in_range, "peak": peak}


def verdict(raw: bytes) -> str:
    """Say which interpretation the bytes support."""
    i16, f32 = as_int16(raw), as_float32(raw)
    if f32 and f32["in_minus1_1"] > 0.98 and i16 and i16["big_jumps"] > 0.2:
        return "FLOAT32 — values sit in [-1,1] as floats, and read as int16 they are noise"
    if i16 and i16["big_jumps"] < 0.05 and i16["near_full"] < 0.5:
        return "INT16 — smooth as 16-bit integers, consistent with speech"
    return "INCONCLUSIVE — see the numbers above"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--out", default="/tmp/voxtral_probe")
    args = parser.parse_args()

    from mistralai.client import Mistral

    client = Mistral(api_key=api_key())
    os.makedirs(args.out, exist_ok=True)
    print(f"text: {args.text!r}  voice: {args.voice}  model: {MODEL}\n")

    # -- 1. wav, non-streaming: Mistral's own declaration of the format ------
    print("=== 1. response_format='wav' (self-describing) ===")
    response = await client.audio.speech.complete_async(
        model=MODEL, input=args.text, voice_id=args.voice, response_format="wav"
    )
    wav_bytes = base64.b64decode(response.audio_data)
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        rate, width, channels, frames = w.getframerate(), w.getsampwidth(), w.getnchannels(), w.getnframes()
        wav_pcm = w.readframes(frames)
    print(f"  container: {len(wav_bytes)} bytes, header says {rate} Hz, {width * 8}-bit, {channels} ch")
    print(f"  audio: {frames} frames = {frames / rate:.2f} s, data chunk {len(wav_pcm)} bytes")
    print(f"  as int16: {as_int16(wav_pcm)}")
    with open(f"{args.out}/from_wav.wav", "wb") as fh:
        fh.write(wav_bytes)

    # -- 2. pcm, streaming: what the integration actually consumes -----------
    print("\n=== 2. response_format='pcm', stream=True (what HomeStral uses) ===")
    deltas: list[bytes] = []
    stream = await client.audio.speech.complete_async(
        model=MODEL, input=args.text, voice_id=args.voice, response_format="pcm", stream=True
    )
    async with stream as events:
        async for event in events:
            name = getattr(event, "event", None) or getattr(getattr(event, "data", None), "type", None)
            if name == "speech.audio.delta":
                deltas.append(base64.b64decode(event.data.audio_data))
            elif name == "speech.audio.done":
                break
    pcm = b"".join(deltas)
    print(f"  {len(deltas)} deltas, sizes {[len(d) for d in deltas][:8]}{'…' if len(deltas) > 8 else ''}")
    print(f"  total {len(pcm)} bytes")
    cumulative = len(deltas) > 1 and deltas[1].startswith(deltas[0])
    print(f"  deltas are {'CUMULATIVE (bug: we concatenate duplicates)' if cumulative else 'incremental'}")
    print(f"  as int16:   {as_int16(pcm)}")
    print(f"  as float32: {as_float32(pcm)}")
    print(f"  VERDICT: {verdict(pcm)}")
    with open(f"{args.out}/from_pcm.raw", "wb") as fh:
        fh.write(pcm)

    # -- 3. The comparison that names the encoding ---------------------------
    print("\n=== 3. comparison ===")
    ratio = len(pcm) / len(wav_pcm) if wav_pcm else float("nan")
    print(f"  pcm bytes / wav data bytes = {len(pcm)} / {len(wav_pcm)} = {ratio:.3f}")
    if 0.97 <= ratio <= 1.03:
        print(f"  => same encoding as the wav container: {rate} Hz, {width * 8}-bit, {channels} ch")
        expected_rate = rate
    elif 1.9 <= ratio <= 2.1:
        print(f"  => pcm carries twice the bytes: 32-bit samples where the wav is {width * 8}-bit")
        expected_rate = rate
    else:
        print("  => neither 1x nor 2x; check the rate and channel count above")
        expected_rate = rate
    duration_if_s16 = len(pcm) / (expected_rate * 2 * channels)
    duration_if_f32 = len(pcm) / (expected_rate * 4 * channels)
    print(f"  duration if 16-bit: {duration_if_s16:.2f} s | if 32-bit float: {duration_if_f32:.2f} s")
    print(f"  the wav says the sentence lasts {frames / rate:.2f} s — the matching one is the truth")

    # -- 4. What the integration hardcodes today -----------------------------
    print("\n=== 4. against the current constants ===")
    from custom_components.homestral.const import TTS_CHANNELS, TTS_SAMPLE_RATE, TTS_SAMPLE_WIDTH

    print(f"  const.py says {TTS_SAMPLE_RATE} Hz, {TTS_SAMPLE_WIDTH * 8}-bit, {TTS_CHANNELS} ch")
    print(f"  Mistral says {rate} Hz, {width * 8}-bit, {channels} ch")
    ok = (TTS_SAMPLE_RATE, TTS_SAMPLE_WIDTH, TTS_CHANNELS) == (rate, width, channels)
    print(f"  => constants are {'correct' if ok else 'WRONG, this is the saturation'}")
    print(f"\naudio written to {args.out}/ for listening")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
