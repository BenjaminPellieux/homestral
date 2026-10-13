"""
Tests unitaires pour le module conversation.py.

conversation.py n'utilise plus de DeviceController : le controle des appareils
passe par HAToolExecutor (tools.py) via la boucle de tools Mistral. On teste
donc les parametres envoyes a ``client.beta.conversations.start_async``
(model, tools, instructions, agent_id) en patchant ``build_ha_context``.
"""

import json

import pytest
import voluptuous as vol
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import MATCH_ALL

from homestral.conversation import MistralConversationEntity
from homestral.const import (
    CONF_AGENT_ID,
    CONF_MAX_TOOL_ITERATIONS,
    CONF_MODEL,
    CONF_USE_AGENT,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOOL_ITERATIONS,
    MAX_TOOL_ITERATIONS,
    MIN_TOOL_ITERATIONS,
)
from homestral.errors import ConversationError
from homestral.tools import ALL_TOOLS


# ---------------------------------------------------------------------------
# Fake SDK entry classes (patched into homestral.conversation)
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
    """Patch the SDK entry classes used by the tool loop's isinstance checks."""
    import homestral.conversation as conv_mod

    monkeypatch.setattr(conv_mod, "FunctionCallEntry", FakeFunctionCallEntry)
    monkeypatch.setattr(conv_mod, "MessageOutputEntry", FakeMessageOutputEntry)
    monkeypatch.setattr(conv_mod, "ToolExecutionEntry", FakeToolExecutionEntry)
    monkeypatch.setattr(conv_mod, "FunctionResultEntry", FakeFunctionResultEntry)


TOO_MANY_STEPS_MESSAGE = "La réponse a nécessité trop d'étapes. Veuillez reformuler."


def _build_entity(entry_data=None):
    """Construit une entite avec un client Mistral mocke (entry.runtime_data)."""
    mock_hass = MagicMock()
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.runtime_data = MagicMock()  # client Mistral
    mock_entry.data = entry_data if entry_data is not None else {
        "api_key": "test",
        CONF_USE_AGENT: False,
    }
    return MistralConversationEntity(mock_hass, mock_entry)


def _make_user_input(text):
    user_input = MagicMock()
    user_input.text = text
    return user_input


@pytest.mark.asyncio
async def test_async_handle_error():
    """Test la gestion des erreurs."""
    entity = _build_entity()

    chat_log = MagicMock()
    chat_log.content = []

    error = ConversationError(
        message="Test error",
        code="TEST_ERROR",
        details={"key": "value"}
    )

    await entity.async_handle_error(chat_log, error)

    assert len(chat_log.content) == 1
    assert "Error: Test error" in chat_log.content[0].content
    assert "Code: TEST_ERROR" in chat_log.content[0].content
    assert "Details: {'key': 'value'}" in chat_log.content[0].content


def test_supported_languages():
    """Test les langues supportées."""
    entity = _build_entity()
    assert entity.supported_languages == MATCH_ALL


@pytest.mark.asyncio
async def test_start_conversation_passes_model_tools_and_instructions():
    """start_conversation envoie model par defaut, ALL_TOOLS et les instructions."""
    entity = _build_entity()  # pas de cle "model" -> DEFAULT_CHAT_MODEL

    response = MagicMock()
    entity._client.beta.conversations.start_async = AsyncMock(return_value=response)

    with patch("homestral.conversation.build_ha_context", new_callable=AsyncMock, return_value="ctx"):
        result = await entity.start_conversation(_make_user_input("Allume la lumière du salon"))

    assert result is response
    entity._client.beta.conversations.start_async.assert_called_once()
    kwargs = entity._client.beta.conversations.start_async.call_args.kwargs
    assert kwargs["inputs"] == "Allume la lumière du salon"
    assert kwargs["instructions"] == "ctx"
    assert kwargs["tools"] is ALL_TOOLS
    assert kwargs["model"] == DEFAULT_CHAT_MODEL
    assert "agent_id" not in kwargs


@pytest.mark.asyncio
async def test_start_conversation_uses_configured_model():
    """Un modele configure dans l'entry est prioritaire sur le defaut."""
    entity = _build_entity({CONF_MODEL: "mistral-small-latest", CONF_USE_AGENT: False})

    entity._client.beta.conversations.start_async = AsyncMock(return_value=MagicMock())

    with patch("homestral.conversation.build_ha_context", new_callable=AsyncMock, return_value="ctx"):
        await entity.start_conversation(_make_user_input("Bonjour"))

    kwargs = entity._client.beta.conversations.start_async.call_args.kwargs
    assert kwargs["model"] == "mistral-small-latest"


@pytest.mark.asyncio
async def test_start_conversation_with_agent_passes_agent_id():
    """Avec use_agent=True, agent_id est envoye et aucun model n'est passe."""
    entity = _build_entity({
        CONF_USE_AGENT: True,
        CONF_AGENT_ID: "agent_123",
    })

    entity._client.beta.conversations.start_async = AsyncMock(return_value=MagicMock())

    with patch("homestral.conversation.build_ha_context", new_callable=AsyncMock, return_value="ctx"):
        await entity.start_conversation(_make_user_input("Bonjour"))

    kwargs = entity._client.beta.conversations.start_async.call_args.kwargs
    assert kwargs["agent_id"] == "agent_123"
    assert "model" not in kwargs
    assert kwargs["tools"] is ALL_TOOLS
    assert kwargs["instructions"] == "ctx"


@pytest.mark.asyncio
async def test_keep_conversation_appends_to_existing_conversation():
    """keep_conversation reutilise le conversation_id via append_async."""
    entity = _build_entity()
    entity._conversation_id = "conv_abc"

    response = MagicMock()
    entity._client.beta.conversations.append_async = AsyncMock(return_value=response)

    with patch("homestral.conversation.build_ha_context", new_callable=AsyncMock, return_value="ctx"):
        result = await entity.keep_conversation(_make_user_input("Et la météo ?"))

    assert result is response
    entity._client.beta.conversations.append_async.assert_called_once()
    kwargs = entity._client.beta.conversations.append_async.call_args.kwargs
    assert kwargs["conversation_id"] == "conv_abc"
    assert kwargs["inputs"] == "Et la météo ?"
    assert kwargs["completion_args"] == {"instructions": "ctx"}


async def _run_endless_tool_loop(entity):
    """Drive _async_handle_message with a model that requests a tool call at
    every turn and never produces a final text answer."""
    func_call = FakeFunctionCallEntry(
        "control_ha_device",
        json.dumps({"entity_id": "light.salon", "command": "turn_on"}),
        tool_call_id="call_001",
    )
    loop_response = MagicMock()
    loop_response.conversation_id = "conv_loop"
    loop_response.outputs = [func_call]

    entity._client.beta.conversations.start_async = AsyncMock(return_value=loop_response)
    entity._client.beta.conversations.append_async = AsyncMock(return_value=loop_response)

    chat_log = MagicMock()
    chat_log.content = []

    with patch("homestral.conversation.build_ha_context", new_callable=AsyncMock, return_value="ctx"), \
         patch("homestral.conversation.conversation.async_get_result_from_chat_log", return_value=MagicMock()), \
         patch.object(entity._tool_executor, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = json.dumps({
            "success": True,
            "entity_id": "light.salon",
            "command": "turn_on",
        })
        await entity._async_handle_message(
            _make_user_input("Allume la lumière du salon"), chat_log
        )

    return chat_log, mock_exec


@pytest.mark.asyncio
async def test_tool_loop_uses_default_max_iterations(fake_entries):
    """Entry sans max_tool_iterations : la boucle tourne DEFAULT_MAX_TOOL_ITERATIONS fois."""
    entity = _build_entity()  # pas de cle max_tool_iterations -> defaut

    chat_log, mock_exec = await _run_endless_tool_loop(entity)

    assert mock_exec.call_count == DEFAULT_MAX_TOOL_ITERATIONS
    assert entity._client.beta.conversations.append_async.call_count == DEFAULT_MAX_TOOL_ITERATIONS
    assert len(chat_log.content) == 1
    assert chat_log.content[0].content == TOO_MANY_STEPS_MESSAGE


@pytest.mark.asyncio
async def test_tool_loop_respects_configured_max_iterations(fake_entries):
    """Entry avec max_tool_iterations=2 : la boucle s'arrete apres 2 iterations
    et l'utilisateur recoit le message 'trop d'étapes'."""
    entity = _build_entity({
        "api_key": "test",
        CONF_USE_AGENT: False,
        CONF_MAX_TOOL_ITERATIONS: 2,
    })

    chat_log, mock_exec = await _run_endless_tool_loop(entity)

    assert mock_exec.call_count == 2
    assert entity._client.beta.conversations.append_async.call_count == 2
    assert len(chat_log.content) == 1
    assert chat_log.content[0].content == TOO_MANY_STEPS_MESSAGE


@pytest.mark.asyncio
async def test_config_flow_max_tool_iterations_schema_bounds():
    """Le schema du config flow borne max_tool_iterations entre MIN et MAX."""
    from homestral.config_flow import HomestralConfigFlow

    flow = HomestralConfigFlow()
    result = await flow.async_step_user(None)
    schema = result["data_schema"]

    base = {"api_key": "test"}
    # Valeur par defaut quand le champ est absent
    assert schema(base)[CONF_MAX_TOOL_ITERATIONS] == DEFAULT_MAX_TOOL_ITERATIONS
    # Bornes acceptees
    assert schema({**base, CONF_MAX_TOOL_ITERATIONS: MIN_TOOL_ITERATIONS})[CONF_MAX_TOOL_ITERATIONS] == MIN_TOOL_ITERATIONS
    assert schema({**base, CONF_MAX_TOOL_ITERATIONS: MAX_TOOL_ITERATIONS})[CONF_MAX_TOOL_ITERATIONS] == MAX_TOOL_ITERATIONS
    # Hors bornes rejetees
    with pytest.raises(vol.Invalid):
        schema({**base, CONF_MAX_TOOL_ITERATIONS: 0})
    with pytest.raises(vol.Invalid):
        schema({**base, CONF_MAX_TOOL_ITERATIONS: 11})


if __name__ == "__main__":
    pytest.main([__file__])
