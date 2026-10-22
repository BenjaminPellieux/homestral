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

HomeStral brings [Mistral AI](https://mistral.ai) to Home Assistant Assist: a conversation agent powered by Mistral Small 4 or Large 4 that can control your devices through tool calling, speech-to-text with Voxtral 3 and text-to-speech with Voxtral TTS 3 — all from a single Mistral API key.

## Features

- **Conversation agent** — Mistral Small 4 by default (the model Mistral runs in its own voice pipeline), with Mistral Large 4 (1M context, multimodal) and Mistral Medium 3.5 also selectable. Each Home Assistant conversation (user, device or satellite) gets its own Mistral conversation.
- **Device control by voice** — the model calls Home Assistant tools (`control_ha_device`, `get_ha_state`, `list_ha_entities`, `get_ha_weather`) with your live home context injected into every request.
- **Speech-to-text** — Voxtral 3 realtime transcription: the audio is streamed to Voxtral while you speak, Voxtral's turn detection ends the utterance as soon as you stop (before Home Assistant's silence timeout), and the names of your exposed entities, areas and floors bias the recognition. Falls back to file transcription (Voxtral Mini or Small Transcribe 3) automatically. 13 languages.
- **Text-to-speech** — Voxtral TTS 3 (`voxtral-mini-tts-3-0`), synthesized sentence by sentence while the answer is still being written so playback starts early, with preset voices per language (Marie for French by default), emotion, speaking pace and expressiveness.
- **Direct voice queries** — "Demande à Homestral …" / "Ask Homestral …" through the `HomestralQuery` intent; the sentence files are installed automatically.
- **Mistral agents** — route conversations through a Mistral agent instead of a plain model.
- **Tool-loop bound** — cap the number of tool calls a single request may trigger (1–10, default 5).
- **Options flow** — change the model, agent and tool-loop bound after setup without re-entering your key.
- **Translated UI** — English and French.

## Requirements

- Home Assistant **2025.11** or newer.
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

## Contributing

Contributions are welcome — see [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for the development setup, test suite and release process, and [DEVELOPMENT.md](DEVELOPMENT.md) for the architecture.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE).

## Acknowledgments

- [Home Assistant](https://www.home-assistant.io/) for the platform.
- [Mistral AI](https://mistral.ai) for the models.
