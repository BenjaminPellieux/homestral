# Development Guide for HomeStral

## Overview
This guide provides technical details about the HomeStral project, including its architecture, modules, and data flows.

## Architecture

### High-Level Architecture
HomeStral is a Home Assistant integration that leverages Mistral AI for voice control and intelligent automation. The architecture consists of the following main components:

1. **STT (Speech-to-Text)**: Handles audio processing and transcription using Voxtral 2 (Voxtral Mini Transcribe 2) via `/v1/audio/transcriptions`, with home-automation context biasing.
2. **TTS (Text-to-Speech)**: Synthesizes speech using Voxtral TTS (`voxtral-mini-tts-2603`) via `/v1/audio/speech`.
3. **Conversation**: Manages asynchronous conversations with the Mistral SDK, including the tool-calling loop and automatic Home Assistant context injection.
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
2. **Audio Processing**: The audio data is processed and converted to the required format (WAV, PCM, 16kHz, 16-bit, mono).
3. **API Call**: The processed audio is sent to the Voxtral 2 transcription endpoint (`/v1/audio/transcriptions`) with a home-automation `context_bias` vocabulary to improve recognition of device names and commands. If the V2 endpoint returns no text, the Voxtral V1 chat API is used as a fallback.
4. **Transcription**: The transcribed text is returned and used for further processing.

#### Conversation Data Flow
1. **User Input**: The user provides input via voice or text.
2. **Context Injection**: A Home Assistant context (current time, local weather, available domains) is built and injected as instructions into every conversation request.
3. **Conversation Start**: A new conversation is started with the Mistral SDK (`beta.conversations.start_async`) using the configured chat model or agent.
4. **Tool Loop**: The assistant may request tool calls (`control_ha_device`, `get_ha_state`, `list_ha_entities`, `get_ha_weather`); `HAToolExecutor` executes them against Home Assistant and the results are appended to the conversation (up to 5 iterations).
5. **Response Handling**: The final response from the API is parsed and formatted.
6. **Conversation Continue**: The conversation is continued with additional user inputs (`beta.conversations.append_async`).

## Modules

### `stt.py`
This module handles speech-to-text functionality using Voxtral 2 (Voxtral Mini Transcribe 2). It includes:
- Audio processing and format conversion (WAV, PCM, 16kHz, 16-bit, mono).
- Transcription via the Voxtral 2 endpoint (`/v1/audio/transcriptions`) with home-automation `context_bias` vocabulary and support for 13 languages, with a fallback to the Voxtral V1 chat API.
- Error handling and logging.

### `conversation.py`
This module manages asynchronous conversations with users via the Mistral SDK (`beta.conversations`). It includes:
- Starting and continuing conversations (`start_async` / `append_async`).
- Automatic Home Assistant context injection (current time, local weather, available domains) into every request.
- A tool-calling loop (up to 5 iterations) that executes FunctionTool calls and appends the results to the conversation.
- Handling user inputs and API responses.
- Error handling and logging.

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
This module registers the `HomestralQuery` intent handler. The free-text `query` slot is sent to the Mistral conversation with the same tool loop as `conversation.py`, and the answer is spoken back.

### `helpers.py`
Shared helpers: `create_mistral_client()` (blocking, run in an executor), `get_option()` and `install_custom_sentences()` (copies the shipped sentence files into `<config>/custom_sentences/<lang>/homestral.yaml` without overwriting, then `conversation.reload` is called).

### `services.yaml`
This file defines the `homestral.control_device` service. Service and field names/descriptions live in `strings.json` / `translations/`.

## Mistral AI SDK

The integration uses the `mistralai` Python SDK v3.x (pinned to `mistralai==3.2.0` in the manifest). The SDK ships two import layouts depending on the installation: the PyPI standard layout (`mistralai.models`) and the Home Assistant musllinux wheel layout (`mistralai.client.models`, a namespace package). Model classes are therefore imported with a try/except fallback covering both layouts:

```python
try:
    from mistralai.models import FunctionCallEntry
except ImportError:
    from mistralai.client.models import FunctionCallEntry
```

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