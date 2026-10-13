"""Tests for the integration setup entry.

Regression: the Mistral client must be built in an executor (its constructor
does blocking importlib.metadata scans) instead of the event loop.
"""

from unittest.mock import MagicMock

import pytest

from homestral import _create_mistral_client, async_setup_entry


def test_create_mistral_client_returns_client():
    try:
        from mistralai import Mistral
    except ImportError:
        from mistralai.client import Mistral
    client = _create_mistral_client("sk-test-key-456")
    assert isinstance(client, Mistral)


@pytest.mark.asyncio
async def test_async_setup_entry_builds_client_in_executor():
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

    entry = MagicMock()
    entry.data = {"api_key": "sk-test-key-456"}

    result = await async_setup_entry(hass, entry)

    assert result is True
    # The client was built via the executor, not inline in the event loop
    assert len(executor_calls) == 1
    _func, args = executor_calls[0]
    assert args == ("sk-test-key-456",)
    assert entry.runtime_data is not None
    assert forwarded == [(entry, ["sensor", "conversation", "stt", "tts"])]
