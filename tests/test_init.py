"""Tests for the integration setup entry.

Regression: the Mistral client must be built in an executor (its constructor
does blocking importlib.metadata scans) instead of the event loop.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.homestral import async_setup_entry
from custom_components.homestral.helpers import create_mistral_client


def test_create_mistral_client_returns_client():
    try:
        from mistralai import Mistral
    except ImportError:
        from mistralai.client import Mistral
    client = create_mistral_client("sk-test-key-456")
    assert isinstance(client, Mistral)


def _make_hass(config_dir):
    hass = MagicMock()
    executor_calls = []

    async def fake_executor_job(func, *args):
        executor_calls.append((func, args))
        return func(*args)

    hass.async_add_executor_job = fake_executor_job

    forwarded = []

    async def fake_forward(entry, platforms):
        forwarded.append((entry, platforms))

    hass.config_entries.async_forward_entry_setups = fake_forward
    hass.config.path = lambda *parts: str(config_dir.joinpath(*parts))
    hass.services.async_call = AsyncMock()
    return hass, executor_calls, forwarded


def _make_entry():
    entry = MagicMock()
    entry.data = {"api_key": "sk-test-key-456"}
    return entry


@pytest.mark.asyncio
async def test_async_setup_entry_builds_client_in_executor(tmp_path):
    hass, executor_calls, forwarded = _make_hass(tmp_path)
    entry = _make_entry()

    result = await async_setup_entry(hass, entry)

    assert result is True
    # The client was built via the executor, not inline in the event loop
    client_calls = [args for func, args in executor_calls if func is create_mistral_client]
    assert client_calls == [("sk-test-key-456",)]
    # One client and one shared turn runner are kept on the entry
    from custom_components.homestral.agent import HomestralRuntime, MistralTurnRunner

    assert isinstance(entry.runtime_data, HomestralRuntime)
    assert isinstance(entry.runtime_data.runner, MistralTurnRunner)
    assert entry.runtime_data.runner._client is entry.runtime_data.client
    assert forwarded == [(entry, ["sensor", "conversation", "stt", "tts"])]


@pytest.mark.asyncio
async def test_async_setup_entry_installs_custom_sentences_once(tmp_path):
    hass, _executor_calls, _forwarded = _make_hass(tmp_path)
    entry = _make_entry()

    await async_setup_entry(hass, entry)

    fr = tmp_path / "custom_sentences" / "fr" / "homestral.yaml"
    en = tmp_path / "custom_sentences" / "en" / "homestral.yaml"
    assert fr.is_file() and en.is_file()
    assert "HomestralQuery" in fr.read_text(encoding="utf-8")
    hass.services.async_call.assert_awaited_once_with("conversation", "reload", blocking=True)

    # Second setup: user edits are preserved and no reload is triggered
    fr.write_text("language: fr\nintents: {}\n", encoding="utf-8")
    hass.services.async_call.reset_mock()

    await async_setup_entry(hass, entry)

    assert fr.read_text(encoding="utf-8") == "language: fr\nintents: {}\n"
    hass.services.async_call.assert_not_awaited()
