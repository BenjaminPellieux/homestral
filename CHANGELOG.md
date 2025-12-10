# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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