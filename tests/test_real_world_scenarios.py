"""
Integration tests for the Mistral tool loop in MistralConversationEntity.

These tests verify that FunctionCallEntry (control_ha_device, get_ha_state, etc.)
flows through _async_handle_message correctly — device control is no longer done
via a keyword parser but via the LLM tool call mechanism.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_function_call_entry(name, arguments, tool_call_id="call_001"):
    """Build a mock FunctionCallEntry."""
    entry = MagicMock()
    entry.__class__.__name__ = "FunctionCallEntry"
    entry.name = name
    entry.arguments = json.dumps(arguments) if isinstance(arguments, dict) else arguments
    entry.tool_call_id = tool_call_id
    return entry


def _make_message_entry(text):
    """Build a mock MessageOutputEntry."""
    entry = MagicMock()
    entry.__class__.__name__ = "MessageOutputEntry"
    entry.content = text
    return entry


def _make_tool_execution_entry(name):
    """Build a mock ToolExecutionEntry (Mistral built-in, e.g. web_search)."""
    entry = MagicMock()
    entry.__class__.__name__ = "ToolExecutionEntry"
    entry.name = name
    entry.arguments = {}
    return entry


def _build_entity(hass=None):
    """Create a MistralConversationEntity with mocked dependencies."""
    from homestral.conversation import MistralConversationEntity

    mock_hass = hass or MagicMock()
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.runtime_data = MagicMock()
    mock_entry.data = {
        "api_key": "test",
        "use_agent": False,
        "model": "mistral-medium-latest",
    }
    entity = MistralConversationEntity(mock_hass, mock_entry)
    return entity


@pytest.mark.asyncio
async def test_tool_loop_control_ha_device():
    """
    When Mistral returns a FunctionCallEntry for control_ha_device, the executor
    is called and the model's follow-up MessageOutputEntry is returned to the user.
    """
    from mistralai.models import FunctionCallEntry, MessageOutputEntry, ToolExecutionEntry

    entity = _build_entity()

    # First API response: FunctionCallEntry asking to turn on the light
    func_call = _make_function_call_entry(
        "control_ha_device",
        {"entity_id": "light.salon", "command": "turn_on"},
    )
    first_response = MagicMock()
    first_response.conversation_id = "conv_001"
    first_response.outputs = [func_call]

    # Tool executor succeeds
    tool_result_json = json.dumps({"success": True, "entity_id": "light.salon", "command": "turn_on"})

    # Second API response: model confirms the action
    msg_entry = _make_message_entry("J'ai allumé la lumière du salon.")
    second_response = MagicMock()
    second_response.conversation_id = "conv_001"
    second_response.outputs = [msg_entry]

    entity._client.beta.conversations.start_async = AsyncMock(return_value=first_response)
    entity._client.beta.conversations.append_async = AsyncMock(return_value=second_response)

    with patch.object(entity._tool_executor, "execute", new_callable=AsyncMock) as mock_exec, \
         patch("homestral.conversation.conversation.async_get_result_from_chat_log") as mock_result, \
         patch("homestral.tools.build_ha_context", new_callable=AsyncMock, return_value="ctx"):
        mock_exec.return_value = tool_result_json
        mock_result.return_value = MagicMock()

        # Patch isinstance checks to use our mocks
        import homestral.conversation as conv_mod
        with patch.object(conv_mod, "FunctionCallEntry", type(func_call)), \
             patch.object(conv_mod, "MessageOutputEntry", type(msg_entry)):

            chat_log = MagicMock()
            chat_log.content = []
            user_input = MagicMock()
            user_input.text = "Allume la lumière du salon"

            await entity._async_handle_message(user_input, chat_log)

    mock_exec.assert_called_once_with(
        "control_ha_device",
        {"entity_id": "light.salon", "command": "turn_on"},
    )
    assert len(chat_log.content) == 1
    assert "allumé" in chat_log.content[0].content.lower()


@pytest.mark.asyncio
async def test_tool_loop_direct_message_no_tool():
    """
    When Mistral answers directly (MessageOutputEntry, no tool call), the content
    is appended to the chat log unchanged.
    """
    from mistralai.models import FunctionCallEntry, MessageOutputEntry

    entity = _build_entity()

    msg_entry = _make_message_entry("Bonjour, comment puis-je vous aider ?")
    response = MagicMock()
    response.conversation_id = "conv_002"
    response.outputs = [msg_entry]

    entity._client.beta.conversations.start_async = AsyncMock(return_value=response)

    with patch("homestral.conversation.conversation.async_get_result_from_chat_log") as mock_result, \
         patch("homestral.tools.build_ha_context", new_callable=AsyncMock, return_value="ctx"):
        mock_result.return_value = MagicMock()

        import homestral.conversation as conv_mod
        with patch.object(conv_mod, "FunctionCallEntry", type(MagicMock())), \
             patch.object(conv_mod, "MessageOutputEntry", type(msg_entry)):

            chat_log = MagicMock()
            chat_log.content = []
            user_input = MagicMock()
            user_input.text = "Bonjour"

            await entity._async_handle_message(user_input, chat_log)

    assert len(chat_log.content) == 1
    assert "Bonjour" in chat_log.content[0].content


@pytest.mark.asyncio
async def test_tool_loop_empty_outputs_returns_default_message():
    """An empty outputs list results in the fallback 'no response' message."""
    entity = _build_entity()

    response = MagicMock()
    response.conversation_id = "conv_003"
    response.outputs = []

    entity._client.beta.conversations.start_async = AsyncMock(return_value=response)

    with patch("homestral.conversation.conversation.async_get_result_from_chat_log") as mock_result, \
         patch("homestral.tools.build_ha_context", new_callable=AsyncMock, return_value="ctx"):
        mock_result.return_value = MagicMock()

        chat_log = MagicMock()
        chat_log.content = []
        user_input = MagicMock()
        user_input.text = "Test vide"

        await entity._async_handle_message(user_input, chat_log)

    assert len(chat_log.content) == 1
    assert chat_log.content[0].content  # some fallback message


@pytest.mark.asyncio
async def test_tool_loop_api_exception_resets_conversation():
    """An API exception appends an error message and resets the conversation ID."""
    entity = _build_entity()
    entity._conversation_id = "existing_conv"

    entity._client.beta.conversations.append_async = AsyncMock(
        side_effect=RuntimeError("API down")
    )

    with patch("homestral.conversation.conversation.async_get_result_from_chat_log") as mock_result, \
         patch("homestral.tools.build_ha_context", new_callable=AsyncMock, return_value="ctx"):
        mock_result.return_value = MagicMock()

        chat_log = MagicMock()
        chat_log.content = []
        user_input = MagicMock()
        user_input.text = "Quelle heure est-il ?"

        await entity._async_handle_message(user_input, chat_log)

    assert entity._conversation_id is None
    assert len(chat_log.content) == 1
    assert "Error" in chat_log.content[0].content


if __name__ == "__main__":
    pytest.main([__file__])
