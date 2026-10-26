"""Shared helpers for the HomeStral integration."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, LANGUAGE_ALIASES

SENTENCES_SOURCE_DIR = Path(__file__).parent / "custom_sentences"


def create_mistral_client(api_key: str):
    """Build the Mistral client and warm everything that blocks (call from an executor).

    The SDK imports its sub-packages lazily, so the very first speech or transcription
    call would otherwise run ``importlib`` scans and build an SSL context inside the
    event loop. Home Assistant detects that and warns, and the stall lands in the middle
    of an utterance. Touching the lazy attributes here moves the cost to setup.
    """
    import ssl

    try:
        from mistralai import Mistral  # PyPI standard install
    except ImportError:
        from mistralai.client import Mistral  # HA musllinux wheel (namespace package)

    client = Mistral(api_key=api_key)
    # Resolve the lazily imported sub-SDKs (audio.speech, audio.transcriptions, chat).
    for attribute in ("speech", "transcriptions"):
        getattr(client.audio, attribute, None)
    # The websocket session builds a default SSL context, which reads the CA bundle.
    ssl.create_default_context()
    return client


def mistral_language(language: str | None) -> str | None:
    """HA language tag (``fr-FR``, ``en_GB``, ``nb``) to the ISO 639-1 code Mistral expects, or None."""
    if not language:
        return None
    code = language.replace("_", "-").split("-")[0].lower()
    return LANGUAGE_ALIASES.get(code, code) or None


def get_option(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Read a setting from entry.options, falling back to entry.data for entries created before options existed."""
    options = getattr(entry, "options", None)
    if isinstance(options, Mapping) and key in options:
        return options[key]
    data = getattr(entry, "data", None)
    if isinstance(data, Mapping):
        return data.get(key, default)
    return default


def install_custom_sentences(target_root: str) -> bool:
    """Copy the shipped sentence files to <config>/custom_sentences/<lang>/homestral.yaml, never overwriting."""
    installed = False
    for source in sorted(SENTENCES_SOURCE_DIR.glob("*.yaml")):
        target = Path(target_root) / source.stem / f"{DOMAIN}.yaml"
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        installed = True
    return installed
