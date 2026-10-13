# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-10-13

### Fixed

- **Security**: The Mistral API key is no longer logged in plaintext by `sensor.py`.
- **Performance**: The Mistral client is now built in an executor during setup, avoiding blocking calls in the event loop (HA `homeassistant.util.loop` warnings).

### Tests

- Added `tests/test_sensor.py` (API key never logged) and `tests/test_init.py` (client built via executor).

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