"""Tests for the config entry diagnostics.

Regression guard: the Mistral API key must never appear in a downloaded
diagnostics report.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.homestral.diagnostics import async_get_config_entry_diagnostics

SECRET = "sk-test-secret-key-123"


def _entry(cache=None, runtime=True):
    entry = MagicMock()
    entry.data = {"api_key": SECRET}
    entry.options = {"model": "mistral-small-latest", "stt_mode": "realtime"}
    entry.version = 2
    entry.runtime_data = SimpleNamespace(cache=cache if cache is not None else {}) if runtime else None
    return entry


@pytest.mark.asyncio
async def test_diagnostics_redacts_the_api_key():
    result = await async_get_config_entry_diagnostics(MagicMock(), _entry())

    assert SECRET not in str(result)
    assert result["entry"]["data"]["api_key"] == "**REDACTED**"
    assert result["entry"]["options"]["model"] == "mistral-small-latest"
    assert result["version"] == 2


@pytest.mark.asyncio
async def test_diagnostics_lists_cache_keys():
    result = await async_get_config_entry_diagnostics(MagicMock(), _entry(cache={"stt_vocabulary": ("x",), "a": 1}))

    assert result["cache_keys"] == ["a", "stt_vocabulary"]


@pytest.mark.asyncio
async def test_diagnostics_without_runtime_data():
    result = await async_get_config_entry_diagnostics(MagicMock(), _entry(runtime=False))

    assert result["cache_keys"] == []
    assert result["entry"]["data"]["api_key"] == "**REDACTED**"
