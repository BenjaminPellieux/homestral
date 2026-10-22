# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.2] - 2026-10-22

Foundations for Voxtral 3 (see `docs/voxtral3-integration-plan.md`); the realtime STT, streamed TTS and streamed reasoning land in the next releases.

### Changed

- **Models**: speech-to-text now uses `voxtral-mini-transcribe-3-0` (Voxtral Mini Transcribe 3) and text-to-speech `voxtral-mini-tts-3-0` (Voxtral TTS 3). The default chat model for new installs is `mistral-small-latest` (Mistral Small 4, the model Mistral runs in its own voice pipeline); `mistral-large-latest` and `mistral-medium-latest` stay selectable. The undocumented `mistral-large-4` id is mapped to `mistral-large-latest` for existing entries.
- **Vocabulary**: the speech-to-text `context_bias` list now holds multi-word phrases (Voxtral 3), such as "volet roulant".
- **Dependencies**: `mistralai[realtime]==3.3.0` (the `realtime` extra brings the websocket client used by the next release); `scripts/setup` also installs the `tts` and `ffmpeg` component requirements so the TTS tests run.
- **Brand**: replaced the placeholder icon with the HomeStral logo (a pixel-art Mistral cat inside a Home Assistant house), shipped as SVG sources plus `icon.png`, `icon@2x.png`, `logo.png` and `logo@2x.png`.
- **Internals**: the conversation entity and the `HomestralQuery` intent share one `MistralTurnRunner` (`agent.py`); SDK calls are awaited directly instead of being wrapped in executors; SDK models are imported from `mistralai.client.models` only.

### Fixed

- **Text-to-speech**: the speech API returns the audio as base64 text; it is now decoded before being handed to Home Assistant (playback failed before). A real preset voice (`voice_592`, Marie) is sent instead of an undocumented id, and the pipeline voice option is honoured.
- **Conversations**: every Home Assistant conversation (user, device, satellite) now gets its own Mistral conversation instead of all sharing one thread; idle threads are dropped after 30 minutes.

### Added

- `scripts/smoke_voxtral3.py`: manual end-to-end check of the Voxtral 3 stack with a real API key (model ids, TTS payload format, batch and realtime transcription, conversation streaming events). Never run in CI.

### Tests

- 98 tests: new `tests/test_tts.py`, `tests/test_agent.py` and `tests/test_config_flow.py`; the conversation and intent tests target the shared runner.

## [0.2.1] - 2026-10-13

First public release, installable through HACS.

### Added

- **HACS packaging**: the integration now lives in `custom_components/homestral/`, with `hacs.json`, a brand icon, an MIT `LICENSE`, and CI workflows (HACS validation, hassfest, ruff, pytest, tag-driven GitHub releases).
- **API key validation**: the config flow checks the key against the Mistral API and reports `invalid_auth` / `cannot_connect` instead of creating a broken entry.
- **Options flow**: the chat model, Mistral agent and tool-loop bound can be changed after setup (Settings → Devices & services → HomeStral → Configure); the entry reloads automatically.
- **Translations**: English and French UI strings for the config flow, options and the `control_device` service.
- **Automatic custom sentences**: the `HomestralQuery` sentence files are installed into `<config>/custom_sentences/{en,fr}/homestral.yaml` on first setup (never overwritten) and the conversation agent is reloaded.
- **Single instance**: the integration declares `single_config_entry`.

### Changed

- **Requirements**: `mistralai==3.2.0` and `pydub==0.25.1` are pinned; the unused `timezonefinder` and `python-dateutil` requirements were removed.
- **Manifest**: valid `codeowners`, `issue_tracker` pointing at the issues page, `loggers`, and only `conversation` as a hard dependency.
- **Services**: the never-implemented `generate_content` service was removed from `services.yaml`; the `HomestralQuery` intent now calls the Mistral conversation directly.
- **Code style**: the code base is formatted and linted with ruff.

### Fixed

- **Security**: the Mistral API key is no longer logged in plaintext by `sensor.py` nor by the config flow.
- **Performance**: the Mistral client is built once in an executor during setup and shared by the conversation, STT and TTS entities (no more blocking client construction in the event loop).
- **Intents**: the `HomestralQuery` intent handler is now actually registered at startup.

### Tests

- Added `tests/test_sensor.py` (API key never logged) and `tests/test_init.py` (client built via executor, custom sentences installed once).

## [0.2.0] - 2026-10-13

### Added

- **Configurable Tool Loop**: New `max_tool_iterations` config flow option bounding the number of tool-call iterations per conversation turn (default: 5, range: 1–10).
- **HomestralQuery Intent**: New `HomestralQuery` intent (`intent.py`) for direct voice queries such as "Demande à Homestral ..." — the free-text query is sent to the Mistral conversation (same tool-calling loop) and the answer is spoken back.
- **Custom Sentences**: Shipped `custom_sentences/fr.yaml` and `custom_sentences/en.yaml` (wildcard `{query}` slot) to enable the voice entry point — copy them to `<config>/custom_sentences/<lang>/homestral.yaml` and restart Home Assistant.

### Tests

- Test suite extended from 39 to 55 tests: tool-loop bounds and config flow schema validation, intent handler paths (service, fallback, errors), custom sentences YAML validation, and hassil recognition of the shipped sentences.

## [0.1.0] - 2026-10-13

### Changed

- **Chat Model**: The default chat model is now `mistral-large-latest` (Mistral Large 4, 1M context window, multimodal).
- **Dependencies**: The `mistralai` package is now required at version `>=3.2.0`.
- **Speech-to-Text**: STT upgraded to Voxtral 2 (Voxtral Mini Transcribe 2 via `/v1/audio/transcriptions`) with home-automation context biasing and 13 supported languages.

### Added

- **Selectable Chat Model**: The config flow now lets you choose the chat model: `mistral-large-latest`, `mistral-large-4`, `mistral-medium-latest`, or `mistral-small-latest`.
- **Voxtral TTS**: Added a text-to-speech platform using Voxtral TTS (`voxtral-mini-tts-2603` via `/v1/audio/speech`).
- **Tool Calling**: Added FunctionTools for Home Assistant control (`control_ha_device`, `get_ha_state`, `list_ha_entities`, `get_ha_weather`) with automatic Home Assistant context injection into conversations.

## [0.0.2] - 2023-11-01

### Added

- **Error Handling**: Added custom exception classes (`HomestralError`, `APIError`, `ConfigurationError`, `AudioProcessingError`, `ConversationError`) for better error management.
- **Logging**: Added structured logging with JSON formatter and configurable log levels.
- **Tests**: Added unit tests for `stt.py` and `conversation.py` using `pytest`.
- **Documentation**: Added `DEVELOPMENT.md` for technical details and `CHANGELOG.md` for tracking changes.
- **Dependencies**: Added `pytest` and `pytest-asyncio` to `requirements.txt` for testing.

### Changed

- **Error Handling**: Updated `stt.py` and `conversation.py` to use custom exceptions and improved error logging.
- **Logging**: Updated logging in `stt.py` and `conversation.py` to use structured logging.
- **Version**: Updated version to `0.0.2` in `manifest.json`.
- **README.md**: Added instructions for running tests and a link to the Development Guide.

### Fixed

- **Error Messages**: Improved error messages with more context and details.
- **Log Messages**: Structured log messages for better debugging and analysis.

## [0.0.1] - 2023-10-01

### Added

- Initial release of HomeStral integration for Home Assistant.
- Basic functionality for voice control and AI conversations using Mistral AI.
- Support for English and French languages.
- Configuration via Home Assistant UI or `configuration.yaml`.

### Changed

- N/A

### Fixed

- N/A