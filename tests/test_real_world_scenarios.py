"""
Integration tests for the Mistral tool loop in MistralConversationEntity.

These tests verify that FunctionCallEntry (control_ha_device, get_ha_state, etc.)
flows through _async_handle_message correctly — device control is no longer done
via a keyword parser but via the LLM tool call mechanism.

The mistralai SDK layout differs between versions (mistralai.models vs
mistralai.client.models), so tests never import model classes from the SDK:
plain fake classes are patched into the homestral.conversation namespace, which
is what the tool loop's isinstance() checks resolve against.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    import custom_components.homestral.conversation as conv_mod

    monkeypatch.setattr(conv_mod, "FunctionCallEntry", FakeFunctionCallEntry)
    monkeypatch.setattr(conv_mod, "MessageOutputEntry", FakeMessageOutputEntry)
    monkeypatch.setattr(conv_mod, "ToolExecutionEntry", FakeToolExecutionEntry)
    monkeypatch.setattr(conv_mod, "FunctionResultEntry", FakeFunctionResultEntry)


def _build_entity(entry_data=None):
    """Create a MistralConversationEntity with a mocked Mistral client."""
    from custom_components.homestral.conversation import MistralConversationEntity

    mock_hass = MagicMock()
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.runtime_data = MagicMock()  # client Mistral
    mock_entry.data = (
        entry_data
        if entry_data is not None
        else {
            "api_key": "test",
            "use_agent": False,
        }
    )
    return MistralConversationEntity(mock_hass, mock_entry)


def _make_chat_log():
    chat_log = MagicMock()
    chat_log.content = []
    return chat_log


def _make_user_input(text):
    user_input = MagicMock()
    user_input.text = text
    return user_input


def _patch_conversation_deps():
    """Patch build_ha_context and the chat-log result helper."""
    return (
        patch("custom_components.homestral.conversation.build_ha_context", new_callable=AsyncMock, return_value="ctx"),
        patch(
            "custom_components.homestral.conversation.conversation.async_get_result_from_chat_log",
            return_value=MagicMock(),
        ),
    )


@pytest.mark.asyncio
async def test_tool_loop_control_ha_device(fake_entries):
    """
    User: "Allume la lumière du salon" -> the model answers with a
    control_ha_device FunctionCallEntry -> the executor runs the tool ->
    the result is appended to the conversation -> the model's follow-up
    MessageOutputEntry is returned to the user.
    """
    entity = _build_entity()

    # First API response: FunctionCallEntry asking to turn on the light
    func_call = FakeFunctionCallEntry(
        "control_ha_device",
        json.dumps({"entity_id": "light.salon", "command": "turn_on"}),
        tool_call_id="call_001",
    )
    first_response = MagicMock()
    first_response.conversation_id = "conv_001"
    first_response.outputs = [func_call]

    # Second API response: model confirms the action
    second_response = MagicMock()
    second_response.conversation_id = "conv_001"
    second_response.outputs = [FakeMessageOutputEntry("J'ai allumé la lumière du salon.")]

    entity._client.beta.conversations.start_async = AsyncMock(return_value=first_response)
    entity._client.beta.conversations.append_async = AsyncMock(return_value=second_response)

    ctx_patch, result_patch = _patch_conversation_deps()
    with ctx_patch, result_patch, patch.object(entity._tool_executor, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = json.dumps(
            {
                "success": True,
                "entity_id": "light.salon",
                "command": "turn_on",
            }
        )

        chat_log = _make_chat_log()
        await entity._async_handle_message(_make_user_input("Allume la lumière du salon"), chat_log)

    # The tool was executed with the parsed arguments
    mock_exec.assert_called_once_with(
        "control_ha_device",
        {"entity_id": "light.salon", "command": "turn_on"},
    )

    # The tool result was sent back to the conversation
    entity._client.beta.conversations.append_async.assert_called_once()
    append_kwargs = entity._client.beta.conversations.append_async.call_args.kwargs
    assert append_kwargs["conversation_id"] == "conv_001"
    result_entries = append_kwargs["inputs"]
    assert len(result_entries) == 1
    assert isinstance(result_entries[0], FakeFunctionResultEntry)
    assert result_entries[0].tool_call_id == "call_001"
    assert json.loads(result_entries[0].result)["success"] is True

    # The conversation continues and the final answer reaches the chat log
    assert entity._conversation_id == "conv_001"
    assert len(chat_log.content) == 1
    assert "allumé" in chat_log.content[0].content.lower()


@pytest.mark.asyncio
async def test_tool_loop_direct_message_no_tool(fake_entries):
    """
    When Mistral answers directly (MessageOutputEntry, no tool call), the content
    is appended to the chat log unchanged and no tool result is sent back.
    """
    entity = _build_entity()

    response = MagicMock()
    response.conversation_id = "conv_002"
    response.outputs = [FakeMessageOutputEntry("Bonjour, comment puis-je vous aider ?")]

    entity._client.beta.conversations.start_async = AsyncMock(return_value=response)

    ctx_patch, result_patch = _patch_conversation_deps()
    with ctx_patch, result_patch:
        chat_log = _make_chat_log()
        await entity._async_handle_message(_make_user_input("Bonjour"), chat_log)

    entity._client.beta.conversations.append_async.assert_not_called()
    assert len(chat_log.content) == 1
    assert chat_log.content[0].content == "Bonjour, comment puis-je vous aider ?"


@pytest.mark.asyncio
async def test_tool_loop_empty_outputs_returns_default_message(fake_entries):
    """An empty outputs list results in the fallback 'no response' message."""
    entity = _build_entity()

    response = MagicMock()
    response.conversation_id = "conv_003"
    response.outputs = []

    entity._client.beta.conversations.start_async = AsyncMock(return_value=response)

    ctx_patch, result_patch = _patch_conversation_deps()
    with ctx_patch, result_patch:
        chat_log = _make_chat_log()
        await entity._async_handle_message(_make_user_input("Test vide"), chat_log)

    assert len(chat_log.content) == 1
    assert chat_log.content[0].content == "Désolé, je n'ai pas reçu de réponse."


@pytest.mark.asyncio
async def test_tool_loop_api_exception_resets_conversation(fake_entries):
    """An API exception appends an error message and resets the conversation ID."""
    entity = _build_entity()
    entity._conversation_id = "existing_conv"

    entity._client.beta.conversations.append_async = AsyncMock(side_effect=RuntimeError("API down"))

    ctx_patch, result_patch = _patch_conversation_deps()
    with ctx_patch, result_patch:
        chat_log = _make_chat_log()
        await entity._async_handle_message(_make_user_input("Quelle heure est-il ?"), chat_log)

    assert entity._conversation_id is None
    assert len(chat_log.content) == 1
    assert "Error" in chat_log.content[0].content


@pytest.mark.asyncio
async def test_tool_loop_builtin_tool_execution(fake_entries):
    """
    A ToolExecutionEntry (built-in Mistral server-side tool such as web_search)
    is not executed client-side: the text of the following MessageOutputEntry
    is returned directly.
    """
    entity = _build_entity()

    response = MagicMock()
    response.conversation_id = "conv_004"
    response.outputs = [
        FakeToolExecutionEntry("web_search", {"q": "météo Paris"}),
        FakeMessageOutputEntry("Il fait beau à Paris."),
    ]

    entity._client.beta.conversations.start_async = AsyncMock(return_value=response)

    ctx_patch, result_patch = _patch_conversation_deps()
    with ctx_patch, result_patch, patch.object(entity._tool_executor, "execute", new_callable=AsyncMock) as mock_exec:
        chat_log = _make_chat_log()
        await entity._async_handle_message(_make_user_input("Quel temps fait-il ?"), chat_log)

    mock_exec.assert_not_called()
    entity._client.beta.conversations.append_async.assert_not_called()
    assert len(chat_log.content) == 1
    assert chat_log.content[0].content == "Il fait beau à Paris."


@pytest.mark.asyncio
async def test_tool_loop_stops_at_configured_max_iterations(fake_entries):
    """
    Scenario: the entry is configured with max_tool_iterations=1 and the model
    keeps requesting the control_ha_device tool. The loop stops after a single
    tool iteration and the final assistant message is the too-many-steps
    fallback.
    """
    entity = _build_entity(
        {
            "api_key": "test",
            "use_agent": False,
            "max_tool_iterations": 1,
        }
    )

    # The model answers with a tool call at every turn, forever
    func_call = FakeFunctionCallEntry(
        "control_ha_device",
        json.dumps({"entity_id": "light.salon", "command": "turn_on"}),
        tool_call_id="call_001",
    )
    loop_response = MagicMock()
    loop_response.conversation_id = "conv_005"
    loop_response.outputs = [func_call]

    entity._client.beta.conversations.start_async = AsyncMock(return_value=loop_response)
    entity._client.beta.conversations.append_async = AsyncMock(return_value=loop_response)

    ctx_patch, result_patch = _patch_conversation_deps()
    with ctx_patch, result_patch, patch.object(entity._tool_executor, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = json.dumps(
            {
                "success": True,
                "entity_id": "light.salon",
                "command": "turn_on",
            }
        )

        chat_log = _make_chat_log()
        await entity._async_handle_message(_make_user_input("Allume la lumière du salon"), chat_log)

    # Exactly one tool iteration despite the model asking again
    mock_exec.assert_called_once_with(
        "control_ha_device",
        {"entity_id": "light.salon", "command": "turn_on"},
    )
    entity._client.beta.conversations.append_async.assert_called_once()

    # The user gets the too-many-steps fallback message
    assert len(chat_log.content) == 1
    assert chat_log.content[0].content == "La réponse a nécessité trop d'étapes. Veuillez reformuler."


if __name__ == "__main__":
    pytest.main([__file__])
