<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/homestral/brand/logo_dark.png">
    <img src="custom_components/homestral/brand/logo.png" alt="HomeStral" width="480">
  </picture>
</p>

# HomeStral — Mistral AI for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/BenjaminPellieux/homestral)](https://github.com/BenjaminPellieux/homestral/releases)
[![License](https://img.shields.io/github/license/BenjaminPellieux/homestral)](LICENSE)
[![HACS](https://github.com/BenjaminPellieux/homestral/actions/workflows/hacs.yaml/badge.svg)](https://github.com/BenjaminPellieux/homestral/actions/workflows/hacs.yaml)
[![Hassfest](https://github.com/BenjaminPellieux/homestral/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/BenjaminPellieux/homestral/actions/workflows/hassfest.yaml)
[![Tests](https://github.com/BenjaminPellieux/homestral/actions/workflows/tests.yaml/badge.svg)](https://github.com/BenjaminPellieux/homestral/actions/workflows/tests.yaml)
[![CodeQL](https://github.com/BenjaminPellieux/homestral/actions/workflows/codeql.yaml/badge.svg)](https://github.com/BenjaminPellieux/homestral/actions/workflows/codeql.yaml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/BenjaminPellieux/homestral/badge)](https://scorecard.dev/viewer/?uri=github.com/BenjaminPellieux/homestral)
[![Security](https://img.shields.io/badge/security-report-blue.svg)](SECURITY.md)

HomeStral brings [Mistral AI](https://mistral.ai) to Home Assistant Assist: a conversation agent powered by Mistral Small 4 or Large 4 that can control your devices through tool calling, speech-to-text with Voxtral 3 and text-to-speech with Voxtral TTS 3 — all from a single Mistral API key.

## Features

- **Conversation agent** — Mistral Small 4 by default (the model Mistral runs in its own voice pipeline), with Mistral Large 4 (1M context, multimodal) and Mistral Medium 3.5 also selectable. Each Home Assistant conversation (user, device or satellite) gets its own Mistral conversation.
- **Calendar** — the assistant can create events ("ajoute un évènement Signature logement le 5 novembre de 14 h à 15 h"), which Home Assistant's own Assist tools cannot do. Needs a writable calendar such as the Local Calendar integration.
- **Device control by voice** — the model acts through Home Assistant's own Assist tools, so it only touches the entities you exposed to Assist and understands "ici" as the area of the satellite you are speaking to. Answers stream into the conversation as they are generated.
- **Speech-to-text** — Voxtral 3 realtime transcription: the audio is streamed to Voxtral while you speak, Voxtral's turn detection ends the utterance as soon as you stop (before Home Assistant's silence timeout), and the names of your exposed entities, areas and floors bias the recognition. Falls back to file transcription (Voxtral Mini or Small Transcribe 3) automatically. 58 languages, Czech, Polish and the Nordic languages included.
- **Text-to-speech** — Voxtral TTS 3 (`voxtral-mini-tts-3-0`), synthesized sentence by sentence while the answer is still being written so playback starts early, with preset voices in 21 languages (Marie for French by default), emotion, speaking pace and expressiveness. Other languages, Czech among them, have no preset voice yet.
- **Direct voice queries** — "Demande à Homestral …" / "Ask Homestral …" through the `HomestralQuery` intent; the sentence files are installed automatically.
- **Mistral agents** — route conversations through a Mistral agent instead of a plain model.
- **Tool-loop bound** — cap the number of tool calls a single request may trigger (1–10, default 5).
- **Options flow** — change the model, agent and tool-loop bound after setup without re-entering your key.
- **Translated UI** — English and French.

## Requirements

- Home Assistant **2026.2.3** or newer (the version the integration is tested against; streamed speech and the LLM API plumbing it relies on are younger than 2025.11).
- A Mistral AI API key from [console.mistral.ai](https://console.mistral.ai) with access to the Mistral Large and Voxtral models.

## Installation

### Option 1: HACS (custom repository)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=BenjaminPellieux&repository=homestral&category=integration)

1. In Home Assistant open **HACS**, click the **⋮** menu (top right) and choose **Custom repositories**.
2. Repository: `https://github.com/BenjaminPellieux/homestral` — Type: **Integration** — click **Add**.
3. Search for **HomeStral** in HACS and click **Download**.
4. **Restart Home Assistant.**

### Option 2: Manual

1. Download the [latest release](https://github.com/BenjaminPellieux/homestral/releases/latest) (or clone the repository).
2. Copy the `custom_components/homestral` folder into `<config>/custom_components/`.
3. **Restart Home Assistant.**

## Setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=homestral)

1. Go to **Settings → Devices & services → Add integration** and search for **HomeStral**.
2. Enter your Mistral API key. It is validated against the Mistral API before the entry is created.
3. Optionally pick the chat model, enable a Mistral agent, and set the maximum number of tool calls per request.

Speech-to-text and text-to-speech entities are created automatically with the same key.

### Changing options later

**Settings → Devices & services → HomeStral → Configure** lets you change the model, agent, tool-loop bound and the speech-to-text settings. Changes are applied immediately.

### Using HomeStral in Assist

Go to **Settings → Voice assistants**, create or edit an assistant and select:

| Setting | Entity |
| --- | --- |
| Conversation agent | **Mistral Conversation** |
| Speech-to-text | **Voxtral STT** |
| Text-to-speech | **Voxtral TTS** |

### Voice pipeline settings

Speech-to-text runs in **realtime** mode by default: each utterance opens a Voxtral 3 realtime session, the pipeline audio is forwarded as it arrives and the session's turn detection ends the utterance as soon as you stop speaking. Keep the assistant's own voice activity detection enabled (the default) as a safety net; Voxtral usually finishes first.

| Option | Default | Use |
| --- | --- | --- |
| Speech-to-text mode | realtime | `batch` uploads the whole recording once Home Assistant detects silence (no turn detection). |
| Turn detection | default | `aggressive` ends turns sooner for short commands, at the price of more cut-offs when you pause; `off` leaves the end of the utterance to Home Assistant. |
| Realtime streaming delay | 480 ms | 240 ms is faster but less accurate, 960 ms more accurate. |
| Speech-to-text language | pipeline | `auto` lets Voxtral detect the language. |
| Batch transcription model | mini | `small` is more accurate; used in batch mode and as the realtime fallback. |
| Custom vocabulary | empty | Names and phrases to recognise, one per line or comma-separated. |
| Recognise exposed entity, area and floor names | on | Adds those names to the recognition vocabulary (capped at 150 entries, refreshed every minute). |
| Chat-audio fallback | off | Last resort when transcription returns nothing: slower, uses the Voxtral chat model. |

The event `homestral_stt_eager_end` is fired when Voxtral believes you have probably finished speaking (before the confirmed end of turn); automations can use it to pre-warm something.

### Voices, emotion and pace

The voice is chosen per Assist pipeline (**Settings → Voice assistants → your assistant → Text-to-speech**) or, when the pipeline leaves it unset, per entry in the options below.

| Option | Default | Use |
| --- | --- | --- |
| Default voice | empty | A Voxtral voice id such as `voice_592` (Marie, French). Empty uses the first preset voice of the spoken language. |
| Default emotion | none | One of the 34 documented emotions (`calm`, `warm`, `urgent`, `playful`, …) applied to every answer. |
| Default speaking pace | none | `very-slow`, `slow`, `moderate`, `fast` or `very-fast`. |
| Expressiveness | 0 | `0` keeps Mistral's default. Between 1.0 and 5.0, higher values give a stronger delivery at the cost of voice similarity and stability. |
| Custom pronunciations | empty | One `word=IPA` per line, for example `Pellieux=p ɛ l j ø`, for names the voice keeps mangling. |

For a one-off announcement, `tts.speak` accepts `emotion` and `pace` in its options:

```yaml
action: tts.speak
target:
  entity_id: tts.voxtral_tts
data:
  media_player_entity_id: media_player.salon
  message: Le portail est resté ouvert.
  options:
    emotion: urgent
    pace: fast
```

The delivery tags are tested in English by Mistral, and expected but untested in French.

### Acting on Home Assistant

The model controls your home through Home Assistant's own Assist tools. Two consequences matter:

- **Only the entities you exposed to Assist can be controlled.** Manage them in **Settings → Voice assistants → Expose**. An entity that is not exposed is invisible to the model.
- **The satellite's area is known**, so "allume la lumière ici" or "ferme les volets de cette pièce" resolve without naming entities.

| Option | Default | Use |
| --- | --- | --- |
| Home Assistant control | `assist` | Which Home Assistant API the model may act through. Clearing it leaves the model with no way to act (answers only). |
| Legacy HomeStral tools | off | Also send `control_ha_device`, `get_ha_state` and `list_ha_entities`. They reach entities that are **not** exposed to Assist, so they stay off unless you upgraded from 0.4.0 or earlier, where they were the only way to act. |
| Custom instructions | empty | Replaces HomeStral's built-in prompt. Empty keeps it (short spoken answers, current time, local weather, tool guidance). |
| Confirm sensitive actions | off | Requires a spoken confirmation before unlocking a door, disarming an alarm or opening a cover: the assistant asks, the microphone stays open, and the action runs only after you answer. |

Upgrading from an earlier release keeps the legacy tools enabled so nothing stops working; turn them off once you have exposed the entities you want the assistant to reach. The `homestral.control_device` service is unaffected either way.

When the assistant ends its answer with a question, Home Assistant keeps the microphone open so you can reply without repeating the wake word.

## Usage

### Talking to the conversation agent

- "Turn on the living room lights"
- "What's the temperature in the bedroom?"
- "Set the thermostat to 22 degrees"
- "What's the weather forecast for tomorrow?"
- "Why is my energy usage higher than usual?"

### Direct voice queries ("Ask Homestral …")

HomeStral ships a `HomestralQuery` intent so the default Assist pipeline can hand a free-text question to Mistral:

- "Demande à Homestral quelle est la météo"
- "Ask Homestral what the weather is"

On first setup the sentence files are installed into your configuration directory:

```
<config>/custom_sentences/en/homestral.yaml
<config>/custom_sentences/fr/homestral.yaml
```

They are never overwritten, so you can customise the trigger phrases freely. Delete a file and reload the integration to restore the defaults. After editing, run the `conversation.reload` service (or restart Home Assistant).

### Service `homestral.control_device`

Call a Home Assistant service on an entity through HomeStral's device controller, for example from an automation:

```yaml
service: homestral.control_device
data:
  config_entry: !input homestral_entry
  device_id: light.living_room
  command: turn_on
  parameters:
    brightness: 200
```

## Models

| Role | Model | Notes |
| --- | --- | --- |
| Chat (default) | `mistral-small-latest` | Mistral Small 4 — sub-second voice turns, Apache 2.0 |
| Chat | `mistral-large-latest` | Mistral Large 4 — flagship, multimodal, 1M context |
| Chat | `mistral-medium-latest` | Mistral Medium 3.5 |
| Speech-to-text (realtime) | `voxtral-mini-transcribe-realtime-3-0` | Voxtral Mini Transcribe Realtime 3 over websocket, turn detection |
| Speech-to-text (batch) | `voxtral-mini-transcribe-3-0` / `voxtral-small-transcribe-3-0` | Voxtral Mini / Small Transcribe 3, batch mode and realtime fallback |
| Speech-to-text (last resort) | `voxtral-small-latest` | Chat completion with audio input, optional |
| Text-to-speech | `voxtral-mini-tts-3-0` | Voxtral TTS 3, preset voices per language |

Entries created with the former `mistral-large-4` id are mapped to `mistral-large-latest` automatically.

### Audio quality

The integration asks Voxtral for `wav` rather than `pcm` and reads the sample rate and width out of the returned header, so the audio format is never assumed. If a future Voxtral release changes it, re-measure with:

```bash
MISTRAL_API_KEY=... .venv/bin/python scripts/probe_voxtral_tts.py
```

For speech recognition, each utterance logs its level:

```
[STT] input 3.29s peak=100% rms=-8.4 dBFS clipped=5 — too hot, lower the microphone gain
```

Speech should sit near -20 dBFS. Much hotter clips and the transcription degrades; much quieter and the model works at the noise floor. Browser microphones with automatic gain are the usual culprit.

## Troubleshooting

Enable debug logging in `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.homestral: debug
```

| Symptom | What to check |
| --- | --- |
| "Invalid API key" during setup | The key was rejected by Mistral — create a new one at console.mistral.ai and make sure it has access to the Large and Voxtral models. |
| "Failed to connect to Mistral AI" | Outbound HTTPS from Home Assistant to `api.mistral.ai` is blocked, or the service is down. |
| Voice command is not transcribed | Assist must send 16 kHz, 16-bit, mono PCM (the default). Check the `[STT]` lines in the debug log. |
| "Ask Homestral …" is not recognised | Make sure `<config>/custom_sentences/<lang>/homestral.yaml` exists and that the assistant language matches (`en` or `fr`). |
| Integration not listed | Confirm the folder is `<config>/custom_components/homestral/`, check the Home Assistant log for import errors and restart. |

Still stuck? [Open an issue](https://github.com/BenjaminPellieux/homestral/issues/new/choose) with redacted logs.

## Security

Found a vulnerability? Please report it privately via [GitHub's private vulnerability reporting](https://github.com/BenjaminPellieux/homestral/security/advisories/new) — see [SECURITY.md](SECURITY.md) for our security policy, supported versions, and disclosure timeline. **Do not open a public issue for security vulnerabilities.**

## Accessibility

HomeStral is a voice-first integration designed to be usable by everyone. See [ACCESSIBILITY.md](ACCESSIBILITY.md) for our commitment, known limitations, and how to report a barrier.

## Contributing

Contributions are welcome — see [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for the development setup, test suite and release process, and [DEVELOPMENT.md](DEVELOPMENT.md) for the architecture. By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE).

## Acknowledgments

- [Home Assistant](https://www.home-assistant.io/) for the platform.
- [Mistral AI](https://mistral.ai) for the models.
