# Accessibility

HomeStral is a **voice-first** Home Assistant integration — accessibility is at
the core of its design, not an afterthought. This document describes our
commitment, supported environments, known limitations, and how to report
barriers.

## Our commitment

We believe smart-home technology should be usable by everyone, including people
with visual, motor, cognitive, or speech disabilities. HomeStral is built on
Home Assistant's Assist pipeline, which is itself designed with accessibility
in mind.

## How HomeStral supports accessibility

| Feature | Accessibility benefit |
| --- | --- |
| **Speech-to-text (Voxtral STT)** | Hands-free control — no need to touch a screen or reach a switch. Supports 13 languages. |
| **Text-to-speech (Voxtral TTS)** | Spoken responses — useful for users with visual impairments or when eyes/hands are occupied. |
| **Conversation agent** | Natural-language commands replace complex UI navigation. "Turn on the living room lights" instead of navigating menus. |
| **Voice entity names** | Home Assistant entity names are spoken and recognised — users can rename entities to natural phrases. |
| **Home-automation vocabulary biasing** | The STT model is biased toward domotics vocabulary (lights, thermostats, shutters...) for better recognition of atypical pronunciations. |
| **Multilingual UI** | English and French translations for the config flow, options, and service descriptions. |
| **Home Assistant ecosystem** | Inherits all of Home Assistant's accessibility features (high-contrast themes, screen-reader support in the companion app, keyboard navigation). |

## Supported environments

- **Home Assistant 2025.11+** (Python 3.13) — required for the integration to load.
- **Assist pipelines** — works with any Assist pipeline (cloud or local STT/TTS can be mixed).
- **Browsers** — the config flow and options UI work in all browsers supported by Home Assistant.
- **Languages** — STT: 13 languages (en, fr, zh, hi, es, ar, pt, ru, de, ja, ko, it, nl). TTS: en, fr, es, de, pt, it, nl, hi, ar. UI: en, fr.

## Known limitations

- **STT accuracy varies by accent and dialect.** The Voxtral model may
  transcribe some accents less accurately. The home-automation vocabulary
  biasing helps but is not exhaustive. Users can extend it via Mistral's
  `context_bias` if needed.
- **Voice-only interaction requires a working microphone.** Users who cannot
  use a microphone can still type in the Assist chat input — the conversation
  agent accepts text.
- **TTS voice is fixed** to the Voxtral default voice (preset voice IDs are
  not yet configurable).
- **No visual feedback** in the integration itself — feedback is spoken via TTS
  or visible in the Home Assistant UI (entity states, conversation history).
- **Custom sentences** for the `HomestralQuery` intent are shipped in English
  and French only. Other languages require manually creating sentence files.

## Reporting a barrier

If you encounter an accessibility barrier:

1. **Search existing issues** — someone may have reported it already:
   [Issues](https://github.com/BenjaminPellieux/homestral/issues?q=is%3Aissue+label%3Aaccessibility)
2. **Open a new issue** with the `accessibility` label:
   [New issue](https://github.com/BenjaminPellieux/homestral/issues/new/choose)
3. **Describe**:
   - What you were trying to do.
   - What barrier you encountered (what happened vs. what you expected).
   - Your environment (HA version, HomeStral version, browser/device, assistive technology used).
   - Any workaround you found.

We aim to acknowledge accessibility reports within **7 days** and will
prioritise fixes that block users from core functionality.

## Roadmap

- [ ] Configurable TTS voice selection (multiple Voxtral preset voices).
- [ ] Additional UI translations (community contributions welcome).
- [ ] Custom sentence templates for more languages.
- [ ] Haptic/visual feedback options for deaf/hard-of-hearing users in the
      conversation UI.

---

*This statement was last updated on 2026-10-22.*
