# Voxtral 3 integration plan for HomeStral

Status: proposal, 2026-10-22. Target release: **0.3.0**.
Verified against: Mistral docs (2026-10-22), `mistralai` SDK 3.3.0 source, Home Assistant 2026.2.3 source, HomeStral `main` at 0.2.1.

Voxtral 3 ships four pillars. This plan maps each one onto a Home Assistant (HA) Assist pipeline stage that HomeStral already owns:

| Pillar | Voxtral 3 capability | HomeStral stage | HA entity / API |
|---|---|---|---|
| Listen | Realtime transcription with turn detection and context biasing | STT | `stt.SpeechToTextEntity.async_process_audio_stream` |
| Reason | Mistral Small 4 / Large 4 with streamed output | Conversation | `ConversationEntity` + `ChatLog.async_add_delta_content_stream` |
| Speak | Voxtral TTS 3, emotion and pace tags, streamed audio | TTS | `TextToSpeechEntity.async_stream_tts_audio` |
| Act | Function calling, multi-step tool loops | Conversation tools | HA LLM API (`llm.AssistAPI`) + HomeStral tools |

The architecture stays "**HA owns the audio transport**": satellites stream PCM to HA, HA calls the STT entity, the conversation entity and the TTS entity one after the other. Mistral's Voice Agents SDK (LiveKit transport) cannot be plugged in as a pipeline stage, so it is only an exploration item (section 9).

---

## 1. Verified facts

Everything below was checked on 2026-10-22. Anything marked **to verify** could not be checked without an API key and is listed again in section 10.

### 1.1 Model identifiers

| Role | Model ID | Aliases | Notes |
|---|---|---|---|
| STT batch (default) | `voxtral-mini-transcribe-3-0` | `voxtral-mini-transcribe-3`, `voxtral-mini-transcribe-latest` | 4B, diarization, segment timestamps, context bias. $0.0035/min |
| STT batch (quality) | `voxtral-small-transcribe-3-0` | `voxtral-small-transcribe-3`, `voxtral-small-transcribe-latest` | Transcription only at launch. $0.0040/min |
| STT realtime | `voxtral-mini-transcribe-realtime-3-0` | `voxtral-mini-transcribe-realtime-3` | WebSocket, turn detection, 80 to 1200 ms or 2400 ms delay. $0.008/min |
| TTS | `voxtral-mini-tts-3-0` | `voxtral-mini-tts-3` | 34 emotion tags, 5 pace tags, 24 kHz mono, mp3/wav/pcm/flac/opus. $13 per 1M characters |
| TTS realtime | `voxtral-mini-tts-realtime-3-0` | none | **Announced but not shipped**: docs page is an empty draft ("parked until TTS Realtime 3 ships"), absent from the models page, no SDK client. Excluded from 0.3.0, see section 9 |
| Audio in chat | `voxtral-small-latest` | | Voxtral 2 era, `input_audio` + tools in one request. Kept as last-resort STT fallback only |
| Chat (voice default) | `mistral-small-latest` | points to Mistral Small 4 `mistral-small-4-0-26-03` | Mistral's own voice agent default, lowest latency |
| Chat (quality) | `mistral-large-latest` | points to Mistral Large 4 `mistral-large-4-0` | current HomeStral default |
| Chat (agentic) | `mistral-medium-latest` | Mistral Medium 3.5 `mistral-medium-3-5-26-04` | |

Alias caveats:

- `voxtral-mini-latest` (current `DEFAULT_STT_MODEL`) is a Voxtral 2 alias and is not documented for Voxtral 3. Pin `voxtral-mini-transcribe-3-0`.
- `voxtral-mini-tts-latest` "will point to Voxtral 3 within a month of GA". Pin `voxtral-mini-tts-3-0`.
- `mistral-large-4` (in `AVAILABLE_CHAT_MODELS`) is not on the models page, which lists `mistral-large-4-0`. **To verify** with `client.models.list()`.
- Voxtral 2 voice slugs (`fr_marie_neutral`, `gb_jane_neutral`, ...) are still accepted by TTS 3. `casual_female` (current `DEFAULT_TTS_VOICE`) is not documented anywhere and is never sent today.

### 1.2 Realtime transcription protocol

Endpoint: `wss://api.mistral.ai/v1/audio/transcriptions/realtime?model=<id>` with `Authorization: Bearer <key>`.

Sequence:

1. Server sends `session.created` with the default session. Wait for it.
2. Client sends one `session.update`. **All settings must be sent before the first audio chunk**; a later update is rejected with an `error` event ("Session fields cannot be changed after audio has started").
3. Client sends `input_audio.append` messages (`{"type": "input_audio.append", "audio": "<base64 pcm>"}`), optionally `input_audio.flush`.
4. Client sends `input_audio.end`.
5. Server sends the last `transcription.text.delta` events then `transcription.done`.

`session.update` fields:

| Field | Type | Default | Constraint |
|---|---|---|---|
| `audio_format` | `{"encoding": "pcm_s16le", "sample_rate": 16000}` | pcm_s16le 16000 | encodings in SDK: `pcm_s16le`, `pcm_s32le`, `pcm_f16le`, `pcm_f32le` |
| `target_streaming_delay_ms` | int | 480 recommended | 80 to 1200, or 2400; other values error |
| `language` | ISO 639-1 (`"fr"`) | auto-detect | invalid code errors |
| `context_bias` | list of strings | `[]` | multi-word phrases and free-form sentences allowed, shares the context window with the audio |
| `turn_detection` | object | not set | **cannot be combined with `diarize`** |
| `diarize` | bool | false | not used by HomeStral |

`turn_detection` parameters (also the exact values of the two documented presets):

| Field | Default | Aggressive |
|---|---|---|
| `start_threshold` | 0.5 | 0.5 |
| `eager_end_threshold` | 0.5 | 0.4 |
| `end_threshold` | 0.33 | 0.33 |
| `min_silence_ms` | 500 | 300 |
| `end_timeout_ms` | 3000 | 2500 |

Constraints: `start_threshold >= eager_end_threshold > end_threshold` and `end_timeout_ms >= min_silence_ms`.

Server events: `session.created`, `session.updated`, `transcription.text.delta {text}`, `transcription.segment` (diarize only), `transcription.language`, `turn.start {time_s}`, `turn.eager_end {time_s}`, `turn.resume {time_s}`, `turn.end {time_s, end_reason: threshold|timeout}`, `transcription.done {text, language, model, usage}`, `error {error: {message, code}}`.

### 1.3 Text to speech

`POST /v1/audio/speech`, SDK `client.audio.speech.complete_async(...)`:

| Parameter | Notes |
|---|---|
| `model` | `voxtral-mini-tts-3-0` |
| `input` | text, may contain inline tags |
| `voice_id` | preset id (`voice_592`), Voxtral 2 slug, or saved cloned voice id. **Required** unless `ref_audio` is given (400 otherwise) |
| `response_format` | `mp3` (default), `wav`, `pcm`, `flac`, `opus`. Output is 24 kHz mono |
| `stream` | `True` returns SSE events `speech.audio.delta` (`event.data.audio_data`, base64) then `speech.audio.done` (`event.data.usage`) |
| `expressiveness` | float 1.0 to 5.0, service default when unset (SDK 3.3.0 only) |
| `phoneme_hints` | mapping word to IPA phonemes, for entity names |
| `conversation_history` | contextual TTS, needs prior user audio, not reachable from an HA TTS entity |

**`SpeechResponse.audio_data` is a base64 string** in both SDK 3.2.0 and 3.3.0. The current `tts.py` returns it to HA as if it were bytes, see section 2.

Tags: `[emotion=<value>]` and `[pace=<value>]`, applied from their position to the next tag or the end of the input, one tag per type per section. Emotions (34): amused, angry, anxious, apologetic, appreciative, assertive, bored, calm, confident, confused, critical, curious, determined, disappointed, disgusted, excited, frustrated, grateful, happy, hopeful, playful, proud, reflective, resigned, sad, sarcastic, skeptical, somber, surprised, tense, tired, urgent, warm, wistful. Paces (5): very-slow, slow, moderate, fast, very-fast. Disfluencies: `[um]`, `[laugh]`, `[sigh]`, `[breath]`. Tags are tested in English and "expected but untested" in French, German, Spanish, Italian, Portuguese and Hindi.

Preset voices used by this plan (voice listing: `client.audio.voices.search(page_size=50)`):

| Language | Voices |
|---|---|
| fr | Marie `voice_592`, Manon `voice_3137`, Lea `voice_589`, Camille `voice_3141` |
| en (US) | Sheila `voice_478`, Margaret `voice_447`, Rob `voice_485`, James `voice_3150` |
| en (GB) | Mary `voice_1787`, Sky `voice_1786`, David `voice_1788`, Harriet `voice_590`, Fred `voice_591`, Hugo `voice_3149`, Howard `voice_3147` |
| es | Elena `voice_483` |
| de | Heidi `voice_481` |
| it | Lorenzo `voice_482` |
| pt | Gabriela `voice_480` |
| nl | Lotte `voice_3145` |
| ar | Maryam `voice_479` |
| hi | Ananya `voice_3139`, Himanshu `voice_3153` |

### 1.4 Conversations API streaming (reason + act)

SDK 3.3.0 `client.beta.conversations` has `start_stream_async`, `append_stream_async`, `restart_stream_async`. Event types: `conversation.response.started`, `message.output.delta` (text), `function.call.delta` (`id`, `name`, `tool_call_id`, `arguments: str`, `output_index`), `tool.execution.started|delta|done` (server-side tools such as `web_search`), `agent.handoff.started|done`, `conversation.response.done`, `conversation.response.error`.

**To verify**: whether `function.call.delta` arrives once with complete `arguments` or incrementally. The runner in section 4.2 accumulates per `output_index` and executes on `conversation.response.done`, which is correct either way.

### 1.5 `mistralai` SDK 3.3.0 realtime surface

- `pip install "mistralai[realtime]"` adds `websockets>=13.0`.
- `client.audio.realtime.connect(model, audio_format, target_streaming_delay_ms)` and `transcribe_stream(audio_stream, model, ...)`.
- `RealtimeConnection.update_session()` only accepts `audio_format` and `target_streaming_delay_ms`. **It cannot send `language`, `context_bias` or `turn_detection`**, and those must be sent before the first chunk.
- The SDK's event parser maps `session.created`, `session.updated`, `error`, `transcription.*` only. `turn.*` events come back as `UnknownRealtimeEvent(type="turn.end", content={...})`.
- The pydantic payload models do exist and cover everything: `RealtimeTranscriptionSessionUpdateMessage`, `RealtimeTranscriptionSessionUpdatePayload` (with `context_bias`, `language`, `turn_detection`), `TurnDetectionConfig`, `AudioFormat`, `RealtimeTranscriptionInputAudioAppend|Flush|End`, and `TurnDetectionStartEvent|EagerEndEvent|ResumeEvent|EndEvent`.

Decision: HomeStral owns the WebSocket (module `voxtral_realtime.py`, built on `websockets`) and reuses the SDK pydantic models for serialization and parsing. No private attribute of the SDK is touched. An upstream issue asking to extend `update_session` is optional.

### 1.6 Home Assistant 2026.2.3 contracts

- STT input: PCM signed 16-bit little-endian, 16 kHz, mono (`assist_pipeline` constants). This is exactly `pcm_s16le / 16000`, so **no transcoding and no pydub**.
- The pipeline's VAD (`VoiceCommandSegmenter`, `silence_seconds` 0.7 by default) ends the audio generator on silence. `_speech_to_text_stream` is documented to "yield audio chunks until VAD detects silence **or speech-to-text completes**": returning early from `async_process_audio_stream` on `turn.end` is supported behaviour.
- `SpeechMetadata.language` can be a full locale (`fr-FR`); Mistral wants ISO 639-1, so normalize to the part before the dash.
- TTS streaming: override `async_stream_tts_audio(TTSAudioRequest(language, options, message_gen)) -> TTSAudioResponse(extension, data_gen)`. HA detects support by the override. The pipeline starts streaming text into TTS after 60 characters (`STREAM_RESPONSE_CHARS`) or after a tool call that follows text. HA converts the engine output with ffmpeg (`-f <extension> -i pipe:0`) when a satellite asks for another format.
- Two core references: `elevenlabs/tts.py` (sentence splitting with `sentence-stream==1.2.0`, synthesis schedule 1 then 3 sentences, mp3 chunks) and `wyoming/tts.py` (emits one WAV header with `nframes=0` then raw PCM, extension `wav`).
- TTS voice option key is `tts.ATTR_VOICE == "voice"`; `async_get_supported_voices(language) -> list[Voice(voice_id, name)]`; the pipeline uses the first voice when none is selected.
- Conversation streaming: `_attr_supports_streaming = True`; `chat_log.async_add_delta_content_stream(agent_id, stream)` consumes dicts `{"role": "assistant"}`, `{"content": "..."}`, `{"tool_calls": [llm.ToolInput(..., external=True)]}` and `{"role": "tool_result", "tool_call_id", "tool_name", "tool_result"}`. Tool calls with `external=False` are executed by HA through `chat_log.llm_api`; with `external=True` the integration executes them and must emit the `tool_result` delta itself (this is what `openai_conversation` does for server-side tools).
- HA LLM API: `chat_log.async_provide_llm_data(user_input.as_llm_context(DOMAIN), llm_hass_api, prompt, extra_system_prompt)`, then `chat_log.llm_api.tools` (voluptuous schemas) converted with `voluptuous_openapi.convert(tool.parameters, custom_serializer=llm_api.custom_serializer)` and executed with `chat_log.llm_api.async_call_tool(ToolInput)`. `voluptuous-openapi==0.2.0` is pinned by HA core. `llm.LLM_API_ASSIST == "assist"`. The Assist API only exposes entities marked "exposed to Assist" and adds area/floor context from `device_id`.
- `chat_log.continue_conversation` is true when the last assistant message ends with a question mark: the satellite keeps listening, which is how a clarifying question or a confirmation becomes a multi-step voice interaction.
- `conversation.async_get_result_from_chat_log(user_input, chat_log)` builds the result (already used).
- Manifest requirements may use pip extras (`adb-shell[async]==0.4.4`, `azure-kusto-data[aio]==4.5.1` in core). HA core pins `websockets>=15.0.1`, compatible with the SDK extra.

---

## 2. Defects in 0.2.1 that the plan fixes first

1. **TTS returns base64 text as audio.** `tts.py` does `audio = response.audio_data` and returns it; the SDK declares `audio_data: str` (base64). Fix: `base64.b64decode(response.audio_data)`. Confirm on a real call (section 10).
2. **One global `_conversation_id` for every user, device and satellite.** All HA conversations are appended to the same Mistral conversation. Fix: map HA `conversation_id` to Mistral `conversation_id` with an expiry (same lifetime as HA chat sessions), reset on error.
3. **Duplicated tool loop** in `conversation.py` and `intent.py`. Fix: single `MistralTurnRunner` in `agent.py`.
4. **Blocking SDK calls wrapped in executors** (`run_in_executor` + sync `complete`). Fix: use `*_async` SDK methods everywhere.
5. **`voxtral-mini-latest` and `casual_female`** are undocumented identifiers. Fix: pin IDs from 1.1 and real voice ids.
6. **`HOME_AUTOMATION_VOCAB` single-word constraint** is gone with Voxtral 3; phrases such as "volet roulant du salon" are now the recommended form. Fix: phrase list + dynamic entity names.
7. **`language` deliberately omitted** for Voxtral 2 ("sending 'fr' caused empty responses"). Voxtral 3 documents `language` as optional ISO 639-1. Fix: send the normalized pipeline language, with an "auto" option, and **re-test** the French case.
8. **`control_ha_device` bypasses the "exposed to Assist" setting**: the model can act on any entity. Fix: route actions through the HA LLM API (section 4.4) and gate the legacy tools behind an option.
9. Repository hygiene already identified: `requirements.txt` lost the `pytest-asyncio>=1.4.0` bump (PR #2 merge), and `hacs.json` declares HA 2025.11.0 while dev requirements pin HA 2026.2.3.

---

## 3. Target architecture

```
satellite ──PCM 16k──▶ HA assist_pipeline
                          │
     ┌────────────────────┼─────────────────────────────┐
     ▼                    ▼                             ▼
 stt.py               conversation.py                tts.py
 VoxtralSttEntity     MistralConversationEntity      VoxtralTtsEntity
     │                    │ (streams deltas to ChatLog)   │
     ▼                    ▼                             ▼
 voxtral_realtime.py  agent.py                       SSE speech.complete(stream=True)
 RealtimeSession      MistralTurnRunner              sentence-stream + WAV header
 (own WebSocket,      conversations start/append     voice presets, tags, expressiveness
  SDK models)         _stream_async, tool loop
     │                    │
     │                    ├── HA LLM API tools (llm.AssistAPI, voluptuous_openapi)
     │                    ├── HomeStral tools (get_ha_weather, web_search, legacy control_ha_device)
     │                    └── context_builder.py (system prompt, exposed entities, vocabulary)
     ▼
 batch fallback: audio.transcriptions.complete_async (WAV via stdlib wave)
 last resort:    chat.complete_async(voxtral-small-latest, input_audio)
```

New modules: `voxtral_realtime.py`, `agent.py`, `context_builder.py`, `voices.py`. Rewritten: `stt.py`, `tts.py`, `conversation.py`, `intent.py`, `config_flow.py`, `const.py`, `strings.json`, `translations/*.json`, `manifest.json`. Removed dependency: `pydub` (and `audioop-lts`).

---

## 4. Detailed design

### 4.1 Listen: realtime STT with turn detection

`voxtral_realtime.py`:

```python
class RealtimeSession:
    """One WebSocket session = one utterance."""

    def __init__(self, api_key, model, *, sample_rate=16000, language=None,
                 context_bias=(), turn_detection=None, streaming_delay_ms=480,
                 connect_timeout=5.0, server_url="https://api.mistral.ai"): ...

    async def __aenter__(self):          # websockets.connect + wait session.created
    async def configure(self):           # send session.update built from
                                         # RealtimeTranscriptionSessionUpdateMessage, wait session.updated
    async def send_audio(self, pcm: bytes)   # RealtimeTranscriptionInputAudioAppend (base64)
    async def end_audio(self)                # RealtimeTranscriptionInputAudioEnd
    def events(self) -> AsyncIterator[RealtimeEvent | TurnEvent]  # parse_realtime_event + turn.* models
    async def close(self)
```

Rules enforced by the class, with unit tests:

- `configure()` must run before `send_audio()`; a second `configure()` raises.
- `turn_detection` and `diarize` are mutually exclusive (we never set `diarize`).
- Preset validation: `start_threshold >= eager_end_threshold > end_threshold`, `end_timeout_ms >= min_silence_ms`.
- `target_streaming_delay_ms` restricted to the documented set.
- Every outbound message is produced by the SDK pydantic models (`model_dump_json()`), every inbound message goes through `mistralai.extra.realtime.connection.parse_realtime_event`, and the four `turn.*` payloads are parsed with the SDK `TurnDetection*Event` models.

`stt.py`, `VoxtralSttEntity.async_process_audio_stream(metadata, stream)`:

1. Build `language = metadata.language.split("-")[0]` unless the option is "auto".
2. Build `context_bias` from `context_builder.async_stt_vocabulary(hass)`: static phrases (`HOME_AUTOMATION_VOCAB`, now multi-word), the user's custom vocabulary option, friendly names of entities exposed to Assist (`async_should_expose(hass, "conversation", entity_id)`), area and floor names. Deduplicate, cap at 150 entries (the list shares the audio context window; a 400 `invalid_request_prompt_too_long` is the failure mode), cache for 60 s.
3. Open a `RealtimeSession` with `turn_detection` from the option (off, default, aggressive).
4. Run a sender task: forward each HA chunk with `send_audio`. Keep the raw PCM in a bounded buffer (60 s) for the batch fallback.
5. Consume events: concatenate `transcription.text.delta`; on `turn.end` send `input_audio.end` and stop the sender (early finish, this is the latency win); on `turn.eager_end` log and fire the HA event `homestral_stt_eager_end` (future pre-warm hook); on `error` close and fall back; on `transcription.done` return `SpeechResult(text, SUCCESS)`.
6. If HA ends the stream first (VAD), send `input_audio.end` and wait for `transcription.done` (bounded by a 10 s timeout).
7. Empty text: return `SpeechResult(None, ERROR)` as today (the pipeline maps it to `stt-no-text-recognized`).

Fallback chain: realtime failure (connect error, `error` event, timeout) → batch `audio.transcriptions.complete_async(model="voxtral-mini-transcribe-3-0", file=File(wav bytes built with stdlib wave), language=..., context_bias=...)` → `chat.complete_async("voxtral-small-latest", input_audio)` as last resort (existing V1 path, kept behind an option because it is slower and not a transcription model).

HA VAD stays enabled as a safety net; turn detection simply ends most utterances earlier. The README will document the recommended pipeline audio settings (VAD on, silence 0.7 s) and the "aggressive" preset for short commands.

Costs: a realtime session lives only for the utterance (a few seconds), so the $0.008/min realtime rate is paid per second of speech, not per hour of listening. Wake word detection stays on the satellite or in HA.

### 4.2 Reason: streamed answers through the Conversations API

`agent.py`, `MistralTurnRunner`:

```python
class MistralTurnRunner:
    def __init__(self, hass, client, entry, tool_executor): ...

    async def async_run(self, chat_log, user_input) -> None:
        """Stream one HA turn: start or append a Mistral conversation, loop on tools."""
        conv_id = self._conversations.get(user_input.conversation_id)   # per HA conversation
        inputs = user_input.text
        for _ in range(max_tool_iterations):
            stream = (client.beta.conversations.start_stream_async(inputs=inputs, model=..., instructions=..., tools=tools)
                      if conv_id is None else
                      client.beta.conversations.append_stream_async(conversation_id=conv_id, inputs=inputs,
                                                                     completion_args={"instructions": ...}))
            async for content in chat_log.async_add_delta_content_stream(agent_id, self._transform(stream)):
                ...
            if not chat_log.unresponded_tool_results:   # HA tracks that for us
                break
            inputs = [FunctionResultEntry(tool_call_id=..., result=json) for each executed call]
```

`_transform(stream)` turns Mistral events into HA deltas:

| Mistral event | HA delta |
|---|---|
| `conversation.response.started` | `{"role": "assistant"}` and remember `conversation_id` |
| `message.output.delta` | `{"content": text}` |
| `function.call.delta` | accumulate per `output_index`; at `conversation.response.done` yield `{"tool_calls": [ToolInput(id=tool_call_id, tool_name, tool_args, external=True)]}`, execute (HA LLM API tool or HomeStral tool), then yield `{"role": "tool_result", ...}` |
| `tool.execution.started/done` (web_search) | `{"tool_calls": [ToolInput(..., external=True)]}` then `{"role": "tool_result", "tool_result": {"status": "done"}}` |
| `conversation.response.error` | raise `HomeAssistantError` (the entity turns it into an error response) |

Parallel calls in one response are executed concurrently with `asyncio.gather`, results appended in one `append_stream_async`.

Model: new entries default to `mistral-small-latest` (Mistral Small 4, the model Mistral uses in its own voice pipeline) for sub-second turns; `mistral-large-latest` stays available. The prompt (`context_builder.py`) asks for short spoken-style answers without markdown, in the pipeline language, and to end with a question only when a clarification is really needed (that question keeps the satellite listening thanks to `continue_conversation`).

The HA `ChatLog` is the transcript of record (history, UI, traces). The Mistral server-side conversation is kept for continuity and for the built-in `web_search` tool, one per HA `conversation_id`, dropped after 30 minutes of inactivity or on error.

`intent.py` (`HomestralQuery`) reuses the runner through a minimal non-streaming adapter so both entry points share one implementation.

### 4.3 Speak: streamed, expressive TTS

`tts.py`, `VoxtralTtsEntity`:

- `_attr_supported_options = [ATTR_VOICE, "emotion", "pace", "expressiveness"]`, `_attr_default_language = "fr"`, `_attr_supported_languages` from the preset table (fr, en, es, de, it, pt, nl, ar, hi, plus the other preset languages).
- `async_get_supported_voices(language)` returns the presets of `voices.py` for that language, with the configured default first. A custom or cloned `voice_id` can be typed in the options.
- `async_stream_tts_audio(request)`:
  1. Split `request.message_gen` into sentences with `sentence_stream.SentenceBoundaryDetector` (same library as HA's ElevenLabs integration), synthesis schedule 1 then 3 then "all available" sentences, exactly like `elevenlabs/tts.py`.
  2. For each batch call `client.audio.speech.complete_async(model="voxtral-mini-tts-3-0", input=text, voice_id=..., response_format="pcm", stream=True, expressiveness=...)` and decode every `speech.audio.delta` (`base64.b64decode(event.data.audio_data)`).
  3. Emit once a WAV header for 24 kHz, 16-bit, mono with `nframes=0` (the Wyoming trick) and then raw PCM; return `TTSAudioResponse("wav", data_gen)`. PCM is chosen over mp3 because the documented time-to-first-audio is about 0.8 s for pcm against about 3 s for mp3, and because concatenating independent mp3 files across sentences is fragile.
- `async_get_tts_audio` (non-streaming path, used by `tts.speak` and cached phrases): `response_format="wav"`, decode base64, return `("wav", bytes)`.
- Emotion and pace, two layers:
  - Service-level: `tts.speak` with `options: {emotion: "urgent", pace: "fast"}` prefixes the input with `[emotion=urgent][pace=fast]`. Values are validated against the documented lists; unknown values are dropped (the API would silently ignore them).
  - Conversation-level, opt-in experimental: the system prompt lets the model start its answer with one emotion tag. The runner strips a leading tag from the ChatLog text so the transcript stays clean, and the TTS entity receives the tag through a per-entry "pending emotion" slot keyed by `conversation_id`... which the TTS request does not carry. Because of that gap, v1 keeps model-chosen emotions as a documented experimental option where the tag is left in the text (visible in the chat transcript, honoured by TTS). The clean solution is HA passing conversation context to TTS, which does not exist today.
  - Default emotion per entry (`tts_default_emotion`, none by default) for people who want a consistently "warm" or "calm" assistant.
- `phoneme_hints` for entity names with odd pronunciations: option "pronunciations" (`word=IPA` per line), Phase 4.
- `conversation_history` (contextual TTS) needs the user's audio, which HA does not hand to the TTS entity: not used.

Satellites that cannot play WAV are already served by HA's ffmpeg conversion (`ATTR_PREFERRED_FORMAT`), nothing to do in HomeStral.

### 4.4 Act: Home Assistant LLM API plus HomeStral tools

- On every turn: `await chat_log.async_provide_llm_data(user_input.as_llm_context(DOMAIN), user_llm_hass_api=options["llm_hass_api"], user_llm_prompt=prompt, user_extra_system_prompt=user_input.extra_system_prompt)`. Default `llm_hass_api = ["assist"]`, exactly like the core OpenAI, Anthropic and Google integrations.
- Tools sent to Mistral = `[FunctionTool(function=Function(name=t.name, description=t.description, parameters=voluptuous_openapi.convert(t.parameters, custom_serializer=llm_api.custom_serializer))) for t in chat_log.llm_api.tools]` + HomeStral extras (`get_ha_weather`, `WebSearchTool()`; legacy `control_ha_device`, `get_ha_state`, `list_ha_entities` only when `legacy_tools` is on).
- Execution: HA tool names go to `chat_log.llm_api.async_call_tool(ToolInput(...))` (validates args with voluptuous, applies area/floor context from `device_id`, respects exposure); HomeStral names go to `HAToolExecutor`.
- What this buys: `HassTurnOn`, `HassTurnOff`, `HassSetPosition`, `HassClimateSetTemperature`, `HassLightSet`, `HassMediaPause`, `GetLiveContext`, calendar and todo tools, all localized and maintained by HA, with the exposure and area semantics users already configure. "Allume la lumière ici" works because the Assist API resolves the satellite's area.
- Multi-step: bounded by `max_tool_iterations` (kept), tool results streamed into the ChatLog so the UI shows them, `GetLiveContext` lets the model check state before acting.
- Confirmation of sensitive actions (locks, alarm, garage): option "confirm sensitive actions". The prompt asks a yes/no question first; `continue_conversation` keeps the mic open; the second turn executes. Phase 4.
- Migration: existing entries get `legacy_tools=True` and `llm_hass_api=["assist"]` through `ConfigFlow.VERSION = 2` + `async_migrate_entry`, so nothing breaks on upgrade; the README documents the deprecation of `control_ha_device` as a model tool (the `homestral.control_device` service is unchanged).

---

## 5. Configuration and options

| Key | Type / values | Default | Used by |
|---|---|---|---|
| `model` | `mistral-small-latest`, `mistral-large-latest`, `mistral-medium-latest` (+ pinned ids after verification) | `mistral-small-latest` for new entries | agent |
| `max_tool_iterations` | 1 to 10 | 5 | agent |
| `use_agent`, `agent_id` | existing | | agent |
| `llm_hass_api` | multi-select of `llm.async_get_apis(hass)` | `["assist"]` | agent |
| `legacy_tools` | bool | false (true after migration) | agent |
| `prompt` | text | built-in | agent |
| `confirm_sensitive_actions` | bool | false | agent (Phase 4) |
| `stt_mode` | `realtime`, `batch` | `realtime` | stt |
| `stt_batch_model` | `mini`, `small` | `mini` | stt |
| `stt_streaming_delay_ms` | 240, 480, 960 | 480 | stt |
| `stt_turn_detection` | `off`, `default`, `aggressive` | `default` | stt |
| `stt_language` | `pipeline`, `auto` | `pipeline` | stt |
| `stt_custom_vocabulary` | text, one phrase per line | empty | stt |
| `stt_bias_entities` | bool | true | stt |
| `stt_chat_fallback` | bool | false | stt |
| `tts_voice` | voice id, free text with presets suggested | `voice_592` (fr) / `voice_478` (en) by language | tts |
| `tts_expressiveness` | 1.0 to 5.0 or unset | unset | tts |
| `tts_default_emotion`, `tts_default_pace` | documented lists or none | none | tts |
| `tts_model_emotions` | bool (experimental) | false | agent + tts |

Translations (`strings.json`, `translations/en.json`, `translations/fr.json`) get every new key, with `data_description` entries explaining the latency trade-offs.

---

## 6. Dependencies and compatibility

- `manifest.json`: `"requirements": ["mistralai[realtime]==3.3.0", "sentence-stream==1.2.0"]`, `"version": "0.3.0"`. `pydub` removed, `audioop-lts` no longer needed.
- `requirements.txt`: same pins plus `pytest>=9.1.1`, `pytest-asyncio>=1.4.0` (restore the lost bump), `websockets` comes with the extra.
- Python 3.13 (HA 2026.2 baseline), `asyncio_mode = "strict"` unchanged.
- `hacs.json`: `homeassistant` minimum stays 2025.11.0 (streaming TTS since 2025.7, `continue_conversation` and `async_provide_llm_data` since 2025.3) unless CI shows otherwise; add a second CI job that installs the minimum HA version so the declared floor is tested.
- hassfest: extras in requirements are accepted (used by core manifests).

---

## 7. Delivery phases

Branch `feat/voxtral3`, one pull request per phase, commits and git operations through the Mistral Vibe agents, commit style `ADD|FIX|UPDATE|REFACTOR <summary>`, no attribution trailers.

### Phase 0: foundations (release 0.2.2, about 1 to 2 days)

Tasks:
1. `scripts/smoke_voxtral3.py` (manual, needs `MISTRAL_API_KEY`): list model ids matching `voxtral|mistral-(small|large|medium)`, batch-transcribe `tests/fixtures/salon.wav`, open one realtime session with turn detection and print events with timestamps, synthesize one sentence in `pcm` with streaming and write `out.wav`, print time-to-first-audio. This script settles every "to verify" item in section 10.
2. Fix TTS base64 decoding; set a real default `voice_id`.
3. Pin `voxtral-mini-transcribe-3-0` and `voxtral-mini-tts-3-0`; replace or verify `mistral-large-4`.
4. Introduce `agent.py` with the current non-streaming loop and make `conversation.py` and `intent.py` use it; map Mistral conversations per HA `conversation_id`.
5. Switch to `*_async` SDK calls, drop `run_in_executor`.
6. Repository hygiene: restore `pytest-asyncio>=1.4.0`, align `hacs.json` or CI matrix, bump SDK to `mistralai==3.3.0`.
7. Multi-word `HOME_AUTOMATION_VOCAB`.

Acceptance: 60 existing tests green after adaptation, smoke script output attached to the PR, TTS audible in HA on a real instance.

### Phase 1: Listen (about 3 to 4 days)

Tasks: `voxtral_realtime.py`, `context_builder.async_stt_vocabulary`, rewrite `stt.py`, options `stt_*`, drop pydub, docs.

Acceptance: fake WebSocket server tests green; on a real satellite, an utterance ending with `turn.end` returns the transcript before HA's VAD timeout (log both timestamps); French with `language="fr"` returns text (regression check of the Voxtral 2 issue); batch fallback exercised by killing the network mid-session in a test.

### Phase 2: Speak (about 2 to 3 days)

Tasks: rewrite `tts.py` with streaming, `voices.py`, options `tts_*`, service-level emotion and pace, docs.

Acceptance: `tts.speak` plays on a media player and on an ESPHome satellite (ffmpeg conversion path); streamed answer starts playing before the LLM finishes (pipeline debug shows `tts_start_streaming`); emotion tag audibly changes delivery; unknown tag values are dropped.

### Phase 3: Reason and Act (about 4 to 5 days)

Tasks: streaming runner, HA LLM API integration, config entry migration v2, `legacy_tools` gate, prompt rewrite, `continue_conversation` behaviour, docs.

Acceptance: "allume la lumière ici" from a satellite with an area works through `HassTurnOn` without entity ids in the prompt; a two-tool request ("ferme les volets et mets le chauffage à 19") executes both in one turn; a question from the model keeps the satellite listening; ChatLog shows tool calls and results; no entity that is not exposed to Assist can be controlled when `legacy_tools` is off.

### Phase 4: polish and release 0.3.0 (about 2 to 3 days)

Tasks: `phoneme_hints` option, sensitive-action confirmation, `turn.eager_end` hook (fire HA event, optional LLM pre-warm experiment), diagnostics (`diagnostics.py` with redacted options and last latencies), README/CHANGELOG/DEVELOPMENT updates, HACS release, tag `0.3.0` (release workflow checks the manifest version).

---

## 8. Test plan

- `tests/test_realtime_session.py`: a fake server started with `websockets.serve` on 127.0.0.1 implementing the protocol (sends `session.created`, asserts the first client message is `session.update`, echoes `session.updated`, streams `transcription.text.delta`, `turn.*`, `transcription.done`, or `error` on demand). Covers settings-before-audio, early stop on `turn.end`, VAD-ended streams, error → fallback, connect timeout, preset validation, every message serialized with SDK models.
- `tests/test_stt.py`: realtime path with the session class injected, batch fallback with a WAV built by `wave`, language normalization (`fr-FR` → `fr`, `auto` → omitted), vocabulary composition from mocked exposed entities and areas, cap and dedupe, empty transcript handling.
- `tests/test_tts.py`: fake SSE async iterator; base64 decoding; exactly one WAV header; sentence scheduling 1 then 3; voice resolution by language and option; tag validation; non-streaming path.
- `tests/test_agent.py`: fake Mistral event streams (text only, one call, batched calls, web_search, error) → expected ChatLog delta sequence; execution through a fake `llm_api`; iteration bound; per-conversation id map and expiry; `function.call.delta` incremental and one-shot variants.
- `tests/test_config_flow.py`: options schema, defaults, migration v1 → v2.
- Existing tests kept or adapted (`test_intents.py`, `test_real_world_scenarios.py`, `test_simple_device_control.py`, `test_api_control.py`, `test_init.py`, `test_sensor.py`).
- CI: current workflows (lint, hassfest, HACS, tests) plus a minimum-HA-version job. The smoke script stays manual and is skipped without a key.

---

## 9. Later explorations (not in 0.3.0)

- **Voxtral TTS Realtime 3**: when the docs and SDK ship, add a `RealtimeTtsSession` behind the same `tts.py` sentence pipeline so text deltas are appended as they arrive instead of per-sentence requests. The entity interface does not change.
- **Mistral Voice Agents sessions** (`client.audio.sessions.create(llm=..., stt=..., tts=..., turn=..., tools=...)`, LiveKit transport, $0.04/min with Small 4): a possible "cloud voice mode" where a custom satellite bridge streams audio directly to Mistral and HomeStral only receives client-side tool calls. It bypasses the HA pipeline (no local wake word, no HA TTS cache, no ChatLog), so it is a separate product decision.
- Diarization and speaker references for multi-user households (not compatible with turn detection in one session, needs an offline second pass).
- Voice cloning for a household voice (`voices.create`, saved id used as `voice_id`).

---

## 10. Verification checklist (needs an API key)

Run `scripts/smoke_voxtral3.py` once and record the answers in the Phase 0 PR:

1. `client.models.list()` contains `voxtral-mini-transcribe-3-0`, `voxtral-mini-transcribe-realtime-3-0`, `voxtral-mini-tts-3-0`; does it contain `mistral-large-4` or only `mistral-large-4-0`? What do `voxtral-mini-latest` and `voxtral-mini-tts-latest` resolve to?
2. `speech.complete(...)`: is `audio_data` base64 (expected) and does `response_format="pcm"` return raw 24 kHz 16-bit mono?
3. Realtime session at `sample_rate=16000`: does `session.updated` echo 16000 (the docs sample shows 24000 after starting at 16000, unexplained)?
4. `language="fr"` in realtime and batch returns text for a French sample (Voxtral 2 regression).
5. `function.call.delta` granularity (one event with full arguments or incremental).
6. Time-to-first-audio pcm versus mp3 on a 15-word sentence.
7. `turn.end` latency after end of speech with the Default and Aggressive presets on three sample commands.
8. Context bias with 150 multi-word entries is accepted (no `invalid_request_prompt_too_long`).

---

## 11. Sources

- https://mistral.ai/news/voxtral-3
- https://docs.mistral.ai/studio/audio/overview
- https://docs.mistral.ai/studio/audio/migrate-from-voxtral-2
- https://docs.mistral.ai/studio/audio/speech-to-text/overview
- https://docs.mistral.ai/studio/audio/speech-to-text/transcribe-in-realtime
- https://docs.mistral.ai/studio/audio/speech-to-text/turn-detection
- https://docs.mistral.ai/studio/audio/speech-to-text/bias-context-and-vocabulary
- https://docs.mistral.ai/studio/audio/speech-to-text/quickstarts/transcribe-in-realtime
- https://docs.mistral.ai/studio/audio/concepts/turns
- https://docs.mistral.ai/studio/audio/text-to-speech/overview
- https://docs.mistral.ai/studio/audio/text-to-speech/generate-speech
- https://docs.mistral.ai/studio/audio/text-to-speech/stream-speech
- https://docs.mistral.ai/studio/audio/text-to-speech/voices
- https://docs.mistral.ai/studio/audio/text-to-speech/emotion-tags
- https://docs.mistral.ai/studio/audio/specs-and-limits/audio-formats
- https://docs.mistral.ai/studio/audio/specs-and-limits/languages
- https://docs.mistral.ai/studio/audio/audio-in-chat
- https://docs.mistral.ai/studio/audio/voice-agents/overview
- https://docs.mistral.ai/getting-started/models/models_overview
- `mistralai` 3.3.0: `mistralai/extra/realtime/{transcription,connection}.py`, `mistralai/client/{speech,transcriptions,conversations,audio_sessions}.py`, `mistralai/client/models/*`
- Home Assistant 2026.2.3: `components/{stt,tts,conversation,assist_pipeline}`, `helpers/llm.py`, `components/{openai_conversation,elevenlabs,wyoming}` as reference implementations
