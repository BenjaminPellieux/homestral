# Development Guide for HomeStral

## Overview
This guide provides technical details about the HomeStral project, including its architecture, modules, and data flows.

## Architecture

### High-Level Architecture
HomeStral is a Home Assistant integration that leverages Mistral AI for voice control and intelligent automation. The architecture consists of the following main components:

1. **STT (Speech-to-Text)**: Streams the pipeline audio to a Voxtral Mini Transcribe Realtime 3 websocket session with turn detection (`voxtral_realtime.py`), with file transcription (`voxtral-mini-transcribe-3-0` or the Small model) as fallback; the recognition vocabulary comes from the exposed entities, areas, floors and custom phrases (`context_builder.py`).
2. **TTS (Text-to-Speech)**: Synthesizes speech using Voxtral TTS 3 (`voxtral-mini-tts-3-0`) via `/v1/audio/speech`, with preset voices per language.
3. **Conversation**: The `MistralTurnRunner` (`agent.py`) runs every turn against the Mistral Conversations API, including the tool-calling loop and automatic Home Assistant context injection, with one Mistral conversation per Home Assistant conversation. The conversation entity and the `HomestralQuery` intent are thin wrappers around it.
4. **Tools**: Defines the Home Assistant FunctionTools (`control_ha_device`, `get_ha_state`, `list_ha_entities`, `get_ha_weather`) and executes them against the live HA state via `HAToolExecutor`.
5. **Sensor**: Provides sensor entities for Home Assistant.
6. **Config Flow**: Validates the API key against Mistral, creates the config entry, and exposes an options flow (model, agent, tool-loop bound).
7. **Intent**: Handles the `HomestralQuery` intent ("Ask Homestral …") and installs the shipped custom sentences at setup.
8. **Services**: Exposes the `homestral.control_device` service.

### Repository layout

```
custom_components/homestral/   the integration (what HACS installs)
  brand/icon.png               HACS brand asset
  custom_sentences/{en,fr}.yaml HomestralQuery sentences, copied to <config>/custom_sentences/<lang>/homestral.yaml
  translations/{en,fr}.json    UI translations (strings.json is the source)
tests/                         pytest suite (imports custom_components.homestral.*)
scripts/setup                  dev dependency installer
.github/workflows/             hacs, hassfest, lint (ruff), tests (pytest), release
```

### Data Flow

#### STT Data Flow
1. **Audio Input**: Audio data is captured from the user's microphone.
2. **Vocabulary**: `context_builder.async_stt_vocabulary()` builds the `context_bias` list (custom phrases, built-in home-automation vocabulary, area and floor names, friendly names of the entities exposed to Assist), capped at 150 entries and cached for a minute.
3. **Realtime session** (default mode): `RealtimeSession` opens `wss://api.mistral.ai/v1/audio/transcriptions/realtime`, waits for `session.created`, sends one `session.update` with the audio format (PCM 16 kHz, what Home Assistant delivers), the streaming delay, the language, the vocabulary and the turn-detection preset, then forwards the pipeline chunks as `input_audio.append` while collecting `transcription.text.delta` events. On `turn.end` the sender stops and `input_audio.end` is sent; on the pipeline's own end of audio the same happens. The transcript is `transcription.done`. `turn.eager_end` fires the `homestral_stt_eager_end` event.
4. **Fallbacks**: a connection error, a server `error` event or a timeout makes the entity transcribe the audio kept aside (plus the rest of the utterance) through `/v1/audio/transcriptions` (WAV built with the standard library). If that returns nothing and the option is enabled, the chat API with audio input (`voxtral-small-latest`) is the last resort.
5. **Transcription**: The transcribed text is returned to the pipeline.

#### Conversation Data Flow
1. **User Input**: The user provides input via voice or text.
2. **Context Injection**: A Home Assistant context (current time, local weather, available domains) is built and injected as instructions into every conversation request.
3. **Conversation Start**: `MistralTurnRunner.async_answer()` looks up the Mistral conversation bound to the Home Assistant `conversation_id`; when there is none (or it expired after 30 minutes idle) a new one is started with the Mistral SDK (`beta.conversations.start_async`) using the configured chat model or agent.
4. **Tool Loop**: The assistant may request tool calls (`control_ha_device`, `get_ha_state`, `list_ha_entities`, `get_ha_weather`); `HAToolExecutor` executes them against Home Assistant and the results are appended to the conversation (up to 5 iterations). Several calls in one response are all executed and returned together.
5. **Response Handling**: The final response from the API is parsed and formatted; the conversation entity appends it to the Home Assistant chat log.
6. **Conversation Continue**: The next turn of the same Home Assistant conversation is appended to the same Mistral conversation (`beta.conversations.append_async`); other users, devices and satellites get their own.

## Modules

### `stt.py`
The `SpeechToTextEntity` (PCM 16 kHz, 16-bit, mono, 13 languages). `async_process_audio_stream()` runs the realtime session (`_transcribe_realtime`, with `_pump_audio` forwarding the chunks and `_collect_transcript` consuming the events), then the batch fallback (`_transcribe_batch`) and the optional chat-audio fallback (`_transcribe_chat`). Timeouts: 60 s for a whole realtime utterance, 10 s for `transcription.done` after `input_audio.end`, 30 s per batch request.

### `voxtral_realtime.py`
`RealtimeSession`, one websocket session per utterance, built on the `websockets` library (installed by the `mistralai[realtime]` extra) and the SDK pydantic models (`RealtimeTranscriptionSessionUpdateMessage`, `RealtimeTranscriptionInputAudioAppend`, `TurnDetection*Event`, ...). It validates the documented constraints before connecting (streaming delay 80 to 1200 ms or 2400 ms, turn-detection thresholds), sends every setting before the first chunk, and parses the `turn.*` events the SDK parser does not know. `TURN_PRESETS` holds the documented default and aggressive presets.

### `context_builder.py`
`async_stt_vocabulary()` (the `context_bias` list described above) and `build_ha_context()` (the system prompt: current time, local weather, available domains, tool instructions).

### `agent.py`
The shared `MistralTurnRunner`, one per config entry (kept in `entry.runtime_data`, a `HomestralRuntime` holding the Mistral client and the runner). It includes:
- Starting and continuing conversations (`beta.conversations.start_async` / `append_async`), with a map from Home Assistant `conversation_id` to Mistral conversation id (dropped after 30 minutes idle or on error).
- Automatic Home Assistant context injection (current time, local weather, available domains) into every request.
- A tool-calling loop (bounded by the `max_tool_iterations` option) that executes FunctionTool calls through `HAToolExecutor` and appends the results to the conversation; built-in server-side tools (web search) are recognised and their answer returned.
- The legacy `mistral-large-4` model id is mapped to `mistral-large-latest` (`const.resolve_chat_model`).

### `conversation.py`
The Home Assistant conversation entity: registers itself as the agent of the config entry, calls `MistralTurnRunner.async_answer()` with the Home Assistant `conversation_id`, appends the answer (or an error message) to the chat log and returns the result.

### `tools.py`
This module defines the tool-calling layer used for voice-driven Home Assistant control. It includes:
- `FunctionTool` definitions for the custom HA tools: `control_ha_device`, `get_ha_state`, `list_ha_entities`, and `get_ha_weather` (alongside Mistral's built-in `web_search` tool).
- `HAToolExecutor`, which dispatches tool calls against the live Home Assistant state and services.
- `build_ha_context()`, which builds the system instructions injected into every conversation.

### `tts.py`
This module provides the Voxtral text-to-speech platform. It includes:
- A `TextToSpeechEntity` that synthesizes speech with Voxtral TTS (`voxtral-mini-tts-2603`) via the `/v1/audio/speech` endpoint.
- Multi-language voice output (French by default).

### `api_control.py`
This module implements the lower-level device control layer used by the tools. It includes:
- `DeviceController`, which resolves entities and devices through the entity and device registries and calls the appropriate Home Assistant services.
- Device info and capability lookups.
- Error handling and logging.

### `sensor.py`
This module provides sensor entities for Home Assistant. It includes:
- Sensor configuration and setup.
- Sensor data management.

### `config_flow.py`
This module handles the configuration flow for the integration. It includes:
- API key validation against the Mistral API (`models.list()` in an executor), mapped to the `invalid_auth` / `cannot_connect` / `unknown` form errors.
- Chat model selection (`mistral-large-latest`, `mistral-large-4`, `mistral-medium-latest`, `mistral-small-latest`).
- An options flow (`HomestralOptionsFlow`) for the model, agent and tool-loop bound; the entry is reloaded when options change.

The API key is stored in `entry.data`, everything else in `entry.options`. `helpers.get_option()` reads options first and falls back to `data` for entries created before the options flow existed.

### `intent.py`
This module registers the `HomestralQuery` intent handler. The free-text `query` slot is sent to the shared `MistralTurnRunner` as a one-shot turn (no conversation binding), and the answer is spoken back.

### `helpers.py`
Shared helpers: `create_mistral_client()` (blocking, run in an executor), `get_option()` and `install_custom_sentences()` (copies the shipped sentence files into `<config>/custom_sentences/<lang>/homestral.yaml` without overwriting, then `conversation.reload` is called).

### `services.yaml`
This file defines the `homestral.control_device` service. Service and field names/descriptions live in `strings.json` / `translations/`.

## Mistral AI SDK

The integration uses the `mistralai` Python SDK v3.x, pinned to `mistralai[realtime]==3.3.0` in the manifest. The `realtime` extra adds the `websockets` library used by the realtime transcription session. Since 3.x the SDK is a namespace package whose canonical import path is `mistralai.client` (`from mistralai.client import Mistral`, `from mistralai.client.models import FunctionCallEntry`); `mistralai.models` and `from mistralai import Mistral` do not resolve, so the code imports from `mistralai.client` only.

All network calls use the `*_async` methods of the SDK and are awaited in the event loop; only the client constructor (blocking `importlib.metadata` scans) runs in an executor at setup.

## Development Setup

### Prerequisites
- Python 3.13 or higher (required by Home Assistant 2025.11+)
- Home Assistant 2025.11 or higher (running in Docker or native)
- Mistral AI API key with access to the `mistral-large` and `voxtral` models

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/BenjaminPellieux/homestral.git
   ```
2. Create a Python 3.13 environment and install the development dependencies:
   ```bash
   uv venv --python 3.13 .venv && source .venv/bin/activate
   PYTHON=python scripts/setup
   ```
3. Copy the integration to your Home Assistant configuration:
   ```bash
   cp -r custom_components/homestral /path/to/homeassistant/config/custom_components/
   ```
4. Restart Home Assistant.

### Running Tests and Lint
```bash
pytest -q
ruff check . && ruff format --check .
```

`scripts/setup` installs the requirements of the Home Assistant `conversation`, `tts` and `ffmpeg` components (hassil, home-assistant-intents, mutagen, ha-ffmpeg) because the tests import those components.

### Smoke test against the real API
`scripts/smoke_voxtral3.py` exercises the Voxtral 3 stack end to end with your key (a few cents per run): model ids, the TTS payload format, batch and realtime transcription of a synthesized sentence, and the conversation streaming events. It is never run in CI.

```bash
MISTRAL_API_KEY=... .venv/bin/python scripts/smoke_voxtral3.py --out smoke_out
```

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for the pull request and release process.

### Contributing
We welcome contributions! Please follow these steps:

1. Fork the repository.
2. Create your feature branch:
   ```bash
   git checkout -b feature/AmazingFeature
   ```
3. Commit your changes:
   ```bash
   git commit -m 'Add some AmazingFeature'
   ```
4. Push to the branch:
   ```bash
   git push origin feature/AmazingFeature
   ```
5. Open a Pull Request.

## Error Handling

### Custom Exceptions
HomeStral uses custom exceptions for error handling. The main exceptions are defined in `errors.py`:

- `HomestralError`: Base class for all HomeStral errors.
- `APIError`: Errors related to the Mistral API.
- `ConfigurationError`: Errors related to configuration.
- `AudioProcessingError`: Errors related to audio processing.
- `ConversationError`: Errors related to conversation management.

### Logging
HomeStral uses structured logging for better error tracking and debugging. The logging configuration is defined in `logging_config.py`:

- **JSON Formatter**: Logs are formatted in JSON for easy parsing and analysis.
- **Log Levels**: Logs can be configured to different levels (DEBUG, INFO, WARNING, ERROR).

## Best Practices

### Code Style
- Follow PEP 8 guidelines for Python code.
- Use descriptive variable and function names.
- Include docstrings for all public functions and classes.

### Testing
- Write unit tests for all new features.
- Write integration tests for critical paths.
- Ensure all tests pass before submitting a Pull Request.

### Documentation
- Update the documentation for any new features or changes.
- Include examples and use cases in the documentation.

## Support

For questions or support, please open an issue on this repository or contact the maintainer.