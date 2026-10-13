"""
Tests unitaires pour le module intent.py (intent HomestralQuery).

Le handler envoie le texte libre (slot "query") à la conversation Mistral via
un appel direct au client (entry.runtime_data), comme conversation.py, et
retourne la réponse en speech.

Comme dans test_conversation.py, les classes SDK mistralai ne sont jamais
importées : des fakes sont patchés dans le namespace homestral.intent, là où la
boucle de tools fait ses isinstance().
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from homeassistant.helpers import intent

from custom_components.homestral.intent import (
    INTENT_HOMESTRAL_QUERY,
    HomestralQueryHandler,
    async_setup_intents,
)

CUSTOM_SENTENCES_DIR = Path(__file__).parent.parent / "custom_components" / "homestral" / "custom_sentences"


# ---------------------------------------------------------------------------
# Fake SDK entry classes (patched into homestral.intent)
# ---------------------------------------------------------------------------


class FakeFunctionCallEntry:
    """Client-side tool call requested by the model (e.g. control_ha_device)."""

    def __init__(self, name, arguments, tool_call_id="call_001"):
        self.name = name
        self.arguments = arguments
        self.tool_call_id = tool_call_id


class FakeMessageOutputEntry:
    """Plain text answer from the model."""

    def __init__(self, content):
        self.content = content


class FakeToolExecutionEntry:
    """Built-in Mistral server-side tool execution (e.g. web_search)."""

    def __init__(self, name, arguments=None):
        self.name = name
        self.arguments = arguments if arguments is not None else {}


class FakeFunctionResultEntry:
    """Result of a client-side tool call, sent back to the model."""

    def __init__(self, tool_call_id, result):
        self.tool_call_id = tool_call_id
        self.result = result


@pytest.fixture
def fake_entries(monkeypatch):
    """Patch the SDK entry classes used by the fallback tool loop's isinstance checks."""
    import custom_components.homestral.intent as intent_mod

    monkeypatch.setattr(intent_mod, "FunctionCallEntry", FakeFunctionCallEntry)
    monkeypatch.setattr(intent_mod, "MessageOutputEntry", FakeMessageOutputEntry)
    monkeypatch.setattr(intent_mod, "ToolExecutionEntry", FakeToolExecutionEntry)
    monkeypatch.setattr(intent_mod, "FunctionResultEntry", FakeFunctionResultEntry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry():
    """Config entry avec un client Mistral mocke (entry.runtime_data)."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"api_key": "test", "use_agent": False}
    entry.runtime_data = MagicMock()  # client Mistral
    return entry


def _make_hass(entry=None, service_result=None, service_side_effect=None):
    """Fake hass : un config entry (ou aucun) et un service generate_content mocke."""
    mock_hass = MagicMock()
    entries = [] if entry is None else [entry]
    mock_hass.config_entries.async_entries.return_value = entries
    if service_side_effect is not None:
        mock_hass.services.async_call = AsyncMock(side_effect=service_side_effect)
    else:
        mock_hass.services.async_call = AsyncMock(return_value=service_result)
    return mock_hass


def _make_intent_obj(hass, query=None):
    """Fake Intent avec un vrai IntentResponse (pour tester le speech)."""
    intent_obj = MagicMock()
    intent_obj.hass = hass
    intent_obj.slots = {} if query is None else {"query": {"value": query, "text": query}}
    intent_obj.create_response = lambda: intent.IntentResponse(language="fr", intent=intent_obj)
    return intent_obj


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_setup_intents_registers_handler(monkeypatch):
    """async_setup_intents enregistre un HomestralQueryHandler."""
    registered = []
    monkeypatch.setattr(
        "homeassistant.helpers.intent.async_register",
        lambda hass, handler: registered.append(handler),
    )

    await async_setup_intents(MagicMock())

    assert len(registered) == 1
    handler = registered[0]
    assert isinstance(handler, HomestralQueryHandler)
    assert handler.intent_type == INTENT_HOMESTRAL_QUERY == "HomestralQuery"


def test_handler_declares_query_slot_schema():
    """Le handler declare le slot 'query'."""
    assert "query" in HomestralQueryHandler.slot_schema


# ---------------------------------------------------------------------------
# Happy path — appel direct au client Mistral (entry.runtime_data)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_falls_back_to_direct_conversation(fake_entries):
    """Service indisponible -> appel direct à client.beta.conversations."""
    entry = _make_entry()
    hass = _make_hass(entry=entry, service_side_effect=Exception("Service not found"))

    conv_response = MagicMock()
    conv_response.conversation_id = "conv_123"
    conv_response.outputs = [FakeMessageOutputEntry("C'est fait, j'ai allumé la lumière.")]
    entry.runtime_data.beta.conversations.start_async = AsyncMock(return_value=conv_response)

    handler = HomestralQueryHandler()
    with patch(
        "custom_components.homestral.intent.build_ha_context",
        new_callable=AsyncMock,
        return_value="ctx",
    ):
        response = await handler.async_handle(_make_intent_obj(hass, "allume la lumière"))

    assert response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert response.speech["plain"]["speech"] == "C'est fait, j'ai allumé la lumière."
    kwargs = entry.runtime_data.beta.conversations.start_async.call_args.kwargs
    assert kwargs["inputs"] == "allume la lumière"
    assert kwargs["instructions"] == "ctx"


@pytest.mark.asyncio
async def test_handler_fallback_executes_tool_calls(fake_entries):
    """La boucle d'outils du fallback exécute control_ha_device puis répond."""
    entry = _make_entry()
    hass = _make_hass(entry=entry, service_side_effect=Exception("Service not found"))

    first = MagicMock()
    first.conversation_id = "conv_123"
    first.outputs = [
        FakeFunctionCallEntry(
            "control_ha_device",
            json.dumps({"entity_id": "light.salon", "command": "turn_on"}),
        )
    ]
    second = MagicMock()
    second.conversation_id = "conv_123"
    second.outputs = [FakeMessageOutputEntry("La lumière du salon est allumée.")]
    entry.runtime_data.beta.conversations.start_async = AsyncMock(return_value=first)
    entry.runtime_data.beta.conversations.append_async = AsyncMock(return_value=second)

    handler = HomestralQueryHandler()
    with (
        patch(
            "custom_components.homestral.intent.build_ha_context",
            new_callable=AsyncMock,
            return_value="ctx",
        ),
        patch("custom_components.homestral.intent.HAToolExecutor") as mock_executor_class,
    ):
        mock_executor = AsyncMock()
        mock_executor_class.return_value = mock_executor
        mock_executor.execute.return_value = json.dumps({"success": True})

        response = await handler.async_handle(_make_intent_obj(hass, "allume la lumière du salon"))

    assert response.response_type == intent.IntentResponseType.QUERY_ANSWER
    assert response.speech["plain"]["speech"] == "La lumière du salon est allumée."
    mock_executor.execute.assert_called_once_with(
        "control_ha_device", {"entity_id": "light.salon", "command": "turn_on"}
    )
    entry.runtime_data.beta.conversations.append_async.assert_called_once()
    inputs = entry.runtime_data.beta.conversations.append_async.call_args.kwargs["inputs"]
    assert len(inputs) == 1
    assert inputs[0].tool_call_id == "call_001"
    assert json.loads(inputs[0].result) == {"success": True}


# ---------------------------------------------------------------------------
# Error paths — le handler ne doit jamais lever d'exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_error_when_service_and_client_fail():
    """Service en erreur + client en erreur -> speech d'erreur."""
    entry = _make_entry()
    hass = _make_hass(entry=entry, service_side_effect=Exception("service down"))
    entry.runtime_data.beta.conversations.start_async = AsyncMock(side_effect=RuntimeError("API Mistral indisponible"))

    handler = HomestralQueryHandler()
    with patch(
        "custom_components.homestral.intent.build_ha_context",
        new_callable=AsyncMock,
        return_value="ctx",
    ):
        response = await handler.async_handle(_make_intent_obj(hass, "allume la lumière"))

    assert response.response_type == intent.IntentResponseType.ERROR
    assert "API Mistral indisponible" in response.speech["plain"]["speech"]


@pytest.mark.asyncio
async def test_handler_error_when_not_configured():
    """Pas de config entry -> speech d'erreur, aucun appel au service."""
    hass = _make_hass(entry=None)
    handler = HomestralQueryHandler()

    response = await handler.async_handle(_make_intent_obj(hass, "allume la lumière"))

    assert response.response_type == intent.IntentResponseType.ERROR
    assert response.speech["plain"]["speech"]
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_handler_error_when_query_slot_missing():
    """Slot query absent -> speech d'erreur, aucun appel au service."""
    hass = _make_hass(entry=_make_entry())
    handler = HomestralQueryHandler()

    response = await handler.async_handle(_make_intent_obj(hass, query=None))

    assert response.response_type == intent.IntentResponseType.ERROR
    assert response.speech["plain"]["speech"]
    hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# Custom sentences — reconnaissance hassil des fichiers shipés
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lang,sample,expected_query",
    [
        (
            "fr",
            "demande à Homestral allume la lumière du salon",
            "allume la lumière du salon",
        ),
        (
            "en",
            "ask Homestral turn on the living room light",
            "turn on the living room light",
        ),
    ],
)
def test_custom_sentences_match_homestral_query(lang, sample, expected_query):
    """Les custom sentences shipés sont reconnus par hassil (wildcard {query})."""
    from hassil import Intents
    from hassil.recognize import recognize_all

    path = CUSTOM_SENTENCES_DIR / f"{lang}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    intents = Intents.from_dict(data)

    results = list(recognize_all(sample, intents))

    assert results, f"no intent matched for {sample!r}"
    assert results[0].intent.name == "HomestralQuery"
    slots = {entity.name: entity.value for entity in results[0].entities_list}
    assert slots.get("query") == expected_query


if __name__ == "__main__":
    pytest.main([__file__])
