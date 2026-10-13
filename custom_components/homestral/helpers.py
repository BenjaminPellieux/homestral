"""Shared helpers for the HomeStral integration."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN

SENTENCES_SOURCE_DIR = Path(__file__).parent / "custom_sentences"


def create_mistral_client(api_key: str):
    """Build the Mistral client (blocking importlib.metadata scans — call from an executor)."""
    try:
        from mistralai import Mistral  # PyPI standard install
    except ImportError:
        from mistralai.client import Mistral  # HA musllinux wheel (namespace package)
    return Mistral(api_key=api_key)


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
