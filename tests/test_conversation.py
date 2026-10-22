"""
Tests unitaires pour le module conversation.py.

L'entite ne garde que la plomberie Home Assistant : la boucle de tools et
l'etat des conversations Mistral vivent dans agent.MistralTurnRunner
(voir test_agent.py). Ici on verifie le cablage entite -> runner -> chat log,
en patchant ``build_ha_context`` dans le module agent et en remplacant les
classes SDK par des fakes la ou le runner fait ses isinstance().
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.const import MATCH_ALL

from custom_components.homestral.agent import HomestralRuntime, MistralTurnRunner
from custom_components.homestral.const import (
    CONF_AGENT_ID,
    CONF_MAX_TOOL_ITERATIONS,
    CONF_MODEL,
    CONF_USE_AGENT,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOOL_ITERATIONS,
    MAX_TOOL_ITERATIONS,
    MIN_TOOL_ITERATIONS,
)
from custom_components.homestral.conversation import MistralConversationEntity
from custom_components.homestral.errors import ConversationError
from custom_components.homestral.tools import ALL_TOOLS

# ---------------------------------------------------------------------------
# Fake SDK entry classes (patched into homestral.agent)
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
    import custom_components.homestral.agent as agent_mod

    monkeypatch.setattr(agent_mod, "FunctionCallEntry", FakeFunctionCallEntry)
    monkeypatch.setattr(agent_mod, "MessageOutputEntry", FakeMessageOutputEntry)
    monkeypatch.setattr(agent_mod, "ToolExecutionEntry", FakeToolExecutionEntry)
    monkeypatch.setattr(agent_mod, "FunctionResultEntry", FakeFunctionResultEntry)


TOO_MANY_STEPS_MESSAGE = "La réponse a nécessité trop d'étapes. Veuillez reformuler."


def _build_entity(entry_data=None):
    """Construit une entite avec un client Mistral mocke dans entry.runtime_data."""
    mock_hass = MagicMock()
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = {}
    mock_entry.data = (
        entry_data
        if entry_data is not None
        else {
            "api_key": "test",
            CONF_USE_AGENT: False,
        }
    )
    client = MagicMock()
    mock_entry.runtime_data = HomestralRuntime(client=client, runner=MistralTurnRunner(mock_hass, mock_entry, client))
    return MistralConversationEntity(mock_hass, mock_entry)


def _make_user_input(text, conversation_id="ha_conv"):
    user_input = MagicMock()
    user_input.text = text
    user_input.conversation_id = conversation_id
    return user_input


def _make_chat_log():
    chat_log = MagicMock()
    chat_log.content = []
    return chat_log


def _patch_deps():
    return (
        patch("custom_components.homestral.agent.build_ha_context", new_callable=AsyncMock, return_value="ctx"),
        patch(
            "custom_components.homestral.conversation.conversation.async_get_result_from_chat_log",
            return_value=MagicMock(),
        ),
    )


def _text_response(conversation_id, text):
    response = MagicMock()
    response.conversation_id = conversation_id
    response.outputs = [FakeMessageOutputEntry(text)]
    return response


@pytest.mark.asyncio
async def test_async_handle_error():
    """Test la gestion des erreurs."""
    entity = _build_entity()

    chat_log = _make_chat_log()

    error = ConversationError(message="Test error", code="TEST_ERROR", details={"key": "value"})

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
async def test_first_turn_passes_model_tools_and_instructions(fake_entries):
    """Premier tour : start_async recoit model par defaut, ALL_TOOLS et les instructions."""
    entity = _build_entity()  # pas de cle "model" -> DEFAULT_CHAT_MODEL
    entity._client.beta.conversations.start_async = AsyncMock(return_value=_text_response("conv_1", "Fait."))

    ctx_patch, result_patch = _patch_deps()
    with ctx_patch, result_patch:
        chat_log = _make_chat_log()
        await entity._async_handle_message(_make_user_input("Allume la lumière du salon"), chat_log)

    kwargs = entity._client.beta.conversations.start_async.call_args.kwargs
    assert kwargs["inputs"] == "Allume la lumière du salon"
    assert kwargs["instructions"] == "ctx"
    assert kwargs["tools"] is ALL_TOOLS
    assert kwargs["model"] == DEFAULT_CHAT_MODEL
    assert "agent_id" not in kwargs
    assert chat_log.content[0].content == "Fait."
    assert chat_log.content[0].agent_id == "test_entry"


@pytest.mark.asyncio
async def test_first_turn_uses_configured_model(fake_entries):
    """Un modele configure dans l'entry est prioritaire sur le defaut."""
    entity = _build_entity({CONF_MODEL: "mistral-large-latest", CONF_USE_AGENT: False})
    entity._client.beta.conversations.start_async = AsyncMock(return_value=_text_response("conv_1", "ok"))

    ctx_patch, result_patch = _patch_deps()
    with ctx_patch, result_patch:
        await entity._async_handle_message(_make_user_input("Bonjour"), _make_chat_log())

    assert entity._client.beta.conversations.start_async.call_args.kwargs["model"] == "mistral-large-latest"


@pytest.mark.asyncio
async def test_first_turn_with_agent_passes_agent_id(fake_entries):
    """Avec use_agent=True, agent_id est envoye et aucun model n'est passe."""
    entity = _build_entity({CONF_USE_AGENT: True, CONF_AGENT_ID: "agent_123"})
    entity._client.beta.conversations.start_async = AsyncMock(return_value=_text_response("conv_1", "ok"))

    ctx_patch, result_patch = _patch_deps()
    with ctx_patch, result_patch:
        await entity._async_handle_message(_make_user_input("Bonjour"), _make_chat_log())

    kwargs = entity._client.beta.conversations.start_async.call_args.kwargs
    assert kwargs["agent_id"] == "agent_123"
    assert "model" not in kwargs
    assert kwargs["tools"] is ALL_TOOLS
    assert kwargs["instructions"] == "ctx"


@pytest.mark.asyncio
async def test_second_turn_appends_to_existing_conversation(fake_entries):
    """Le second tour d'une meme conversation HA reutilise le conversation_id via append_async."""
    entity = _build_entity()
    entity._client.beta.conversations.start_async = AsyncMock(return_value=_text_response("conv_abc", "a"))
    entity._client.beta.conversations.append_async = AsyncMock(return_value=_text_response("conv_abc", "b"))

    ctx_patch, result_patch = _patch_deps()
    with ctx_patch, result_patch:
        await entity._async_handle_message(_make_user_input("Bonjour"), _make_chat_log())
        chat_log = _make_chat_log()
        await entity._async_handle_message(_make_user_input("Et la météo ?"), chat_log)

    entity._client.beta.conversations.start_async.assert_called_once()
    kwargs = entity._client.beta.conversations.append_async.call_args.kwargs
    assert kwargs["conversation_id"] == "conv_abc"
    assert kwargs["inputs"] == "Et la météo ?"
    assert kwargs["completion_args"] == {"instructions": "ctx"}
    assert chat_log.content[0].content == "b"


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

    chat_log = _make_chat_log()

    ctx_patch, result_patch = _patch_deps()
    with (
        ctx_patch,
        result_patch,
        patch.object(entity._runner._tool_executor, "execute", new_callable=AsyncMock) as mock_exec,
    ):
        mock_exec.return_value = json.dumps(
            {
                "success": True,
                "entity_id": "light.salon",
                "command": "turn_on",
            }
        )
        await entity._async_handle_message(_make_user_input("Allume la lumière du salon"), chat_log)

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
    entity = _build_entity(
        {
            "api_key": "test",
            CONF_USE_AGENT: False,
            CONF_MAX_TOOL_ITERATIONS: 2,
        }
    )

    chat_log, mock_exec = await _run_endless_tool_loop(entity)

    assert mock_exec.call_count == 2
    assert entity._client.beta.conversations.append_async.call_count == 2
    assert len(chat_log.content) == 1
    assert chat_log.content[0].content == TOO_MANY_STEPS_MESSAGE


@pytest.mark.asyncio
async def test_config_flow_max_tool_iterations_schema_bounds():
    """Le schema du config flow borne max_tool_iterations entre MIN et MAX."""
    from custom_components.homestral.config_flow import HomestralConfigFlow

    flow = HomestralConfigFlow()
    result = await flow.async_step_user(None)
    schema = result["data_schema"]

    base = {"api_key": "test"}
    # Valeur par defaut quand le champ est absent
    assert schema(base)[CONF_MAX_TOOL_ITERATIONS] == DEFAULT_MAX_TOOL_ITERATIONS
    # Bornes acceptees
    assert (
        schema({**base, CONF_MAX_TOOL_ITERATIONS: MIN_TOOL_ITERATIONS})[CONF_MAX_TOOL_ITERATIONS] == MIN_TOOL_ITERATIONS
    )
    assert (
        schema({**base, CONF_MAX_TOOL_ITERATIONS: MAX_TOOL_ITERATIONS})[CONF_MAX_TOOL_ITERATIONS] == MAX_TOOL_ITERATIONS
    )
    # Hors bornes rejetees
    with pytest.raises(vol.Invalid):
        schema({**base, CONF_MAX_TOOL_ITERATIONS: 0})
    with pytest.raises(vol.Invalid):
        schema({**base, CONF_MAX_TOOL_ITERATIONS: 11})


if __name__ == "__main__":
    pytest.main([__file__])
