"""Diagnostics support for HomeStral config entries.

Exposes ``async_get_config_entry_diagnostics`` so Home Assistant can include a
redacted snapshot of an entry (data, options, version and runtime cache keys)
in downloaded diagnostics reports. The API key is always redacted.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

TO_REDACT = {"api_key"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry, with sensitive data redacted."""
    # runtime_data is absent while the entry is not loaded, and its cache is lazily filled.
    cache = getattr(getattr(entry, "runtime_data", None), "cache", None)
    return {
        "entry": async_redact_data({"data": dict(entry.data), "options": dict(entry.options)}, TO_REDACT),
        "version": entry.version,
        "cache_keys": sorted(cache) if isinstance(cache, dict) else [],
    }
