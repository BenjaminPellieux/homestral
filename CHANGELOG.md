# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-10-22

Phase 2 of the Voxtral 3 plan: speak.

### Added

- **Streamed text-to-speech**: the Assist pipeline now streams the conversation answer into the text-to-speech entity. The text is split into sentences, synthesized in batches (the first sentence immediately, then up to three, then everything available) and returned as one streaming WAV: a header with `nframes=0` followed by raw 24 kHz PCM, so playback starts before the model has finished writing.
- **Expressive delivery**: new options for a default voice, a default emotion (the 34 documented values), a default speaking pace (`very-slow` to `very-fast`) and expressiveness (1.0 to 5.0). `tts.speak` also accepts per-request `emotion` and `pace` options. The tags are applied to the first sentence batch, so the whole answer keeps the style.

### Changed

- **Streaming format**: the streamed path requests `pcm` (time to first audio about 0.8 s, against about 3 s for mp3); the one-shot path keeps `wav` so Home Assistant can cache it.
- **Dependencies**: `sentence-stream==1.3.0` added to the manifest (the sentence splitter Home Assistant itself uses for streamed speech).

### Tests

- 147 tests: `tests/test_tts.py` covers the streaming path (exactly one WAV header, the batching schedule, first-batch-only tags, truncation when the API fails mid-stream, unknown tag values dropped) and the one-shot path.

## [0.3.0] - 2026-10-22

Phase 1 of the Voxtral 3 plan: listen. Speech-to-text now runs on Voxtral Mini Transcribe Realtime 3.

### Added

- **Realtime speech-to-text** (`voxtral_realtime.py`): each utterance opens a Voxtral 3 realtime websocket session; the pipeline audio (PCM 16 kHz) is forwarded as it arrives, Voxtral's turn detection ends the utterance on `turn.end` before Home Assistant's silence timeout, and the transcript is taken from `transcription.done`. HomeStral owns the socket (the SDK cannot send `language`, `context_bias` or `turn_detection`, which must precede the first chunk) and reuses the SDK models for every message.
- **Recognition vocabulary from your home** (`context_builder.py`): the friendly names of the entities exposed to Assist, your area and floor names and your custom phrases are sent as multi-word `context_bias`, capped at 150 entries and refreshed every minute.
- **Speech-to-text options**: mode (realtime or batch), turn-detection preset (off, default, aggressive), streaming delay (240, 480 or 960 ms), language (pipeline or auto), batch model (mini or small), custom vocabulary, entity-name biasing, chat-audio fallback. English and French descriptions.
- **Event** `homestral_stt_eager_end` fired on Voxtral's `turn.eager_end`.

### Changed

- **Fallback chain**: realtime failure (connection, server error, timeout) falls back to file transcription with the audio captured so far plus the rest of the utterance; the chat-audio path is now opt-in.
- **Language**: the pipeline language is sent as ISO 639-1 (`fr-FR` becomes `fr`); `auto` lets Voxtral detect it.
- **Dependencies**: `pydub` removed (raw PCM goes straight to the API, the WAV fallback uses the standard library); the manifest requires `mistralai[realtime]==3.3.0` only.

### Tests

- 129 tests: `tests/test_realtime_session.py` drives the session against a fake websocket server (settings before audio, turn events, early end, errors, timeouts, rejected handshake), `tests/test_stt.py` covers the realtime path, the fallbacks and the options, `tests/test_context_builder.py` the vocabulary builder.

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