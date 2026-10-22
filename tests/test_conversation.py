"""
Tests unitaires pour le module conversation.py.

L'entite ne garde que la plomberie Home Assistant : la boucle de tools, le
streaming et l'etat des conversations Mistral vivent dans
agent.MistralTurnRunner (voir test_agent.py). Ici on verifie le cablage
entite -> runner -> chat log et la remontee des erreurs.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from conftest import FakeChatLog, FakeLLMApi, make_user_input
from homeassistant.const import MATCH_ALL

from custom_components.homestral.agent import HomestralRuntime, MistralTurnRunner
from custom_components.homestral.const import (
    CONF_MAX_TOOL_ITERATIONS,
    CONF_USE_AGENT,
    DEFAULT_MAX_TOOL_ITERATIONS,
    MAX_TOOL_ITERATIONS,
    MIN_TOOL_ITERATIONS,
)
from custom_components.homestral.conversation import MistralConversationEntity
from custom_components.homestral.errors import ConversationError


def _build_entity(entry_data=None, client=None):
    """Construit une entite avec un client Mistral mocke dans entry.runtime_data."""
    mock_hass = MagicMock()
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = {}
    mock_entry.data = entry_data if entry_data is not None else {"api_key": "test", CONF_USE_AGENT: False}
    client = client or MagicMock()
    mock_entry.runtime_data = HomestralRuntime(client=client, runner=MistralTurnRunner(mock_hass, mock_entry, client))
    return MistralConversationEntity(mock_hass, mock_entry)


@pytest.mark.asyncio
async def test_async_handle_error():
    """Test la gestion des erreurs."""
    entity = _build_entity()
    chat_log = FakeChatLog()

    error = ConversationError(message="Test error", code="TEST_ERROR", details={"key": "value"})

    await entity.async_handle_error(chat_log, error)

    assert len(chat_log.content) == 2  # prompt systeme + message d'erreur
    # Internal error details are NOT leaked to the user — only a generic message.
    assert "Désolé, une erreur est survenue" in chat_log.content[-1].content
    assert "Test error" not in chat_log.content[-1].content
    assert "TEST_ERROR" not in chat_log.content[-1].content


def test_supported_languages():
    """Test les langues supportées."""
    entity = _build_entity()
    assert entity.supported_languages == MATCH_ALL


def test_entity_advertises_streaming():
    """L'entite annonce le streaming : le pipeline parle avant la fin de la reponse."""
    assert _build_entity().supports_streaming is True


@pytest.mark.asyncio
async def test_handle_message_delegates_to_the_streaming_runner():
    """_async_handle_message passe le chat log et l'entree au runner."""
    entity = _build_entity()
    entity._runner.async_run_streaming = AsyncMock()
    chat_log = FakeChatLog(FakeLLMApi())
    user_input = make_user_input("Allume la lumière du salon")

    with patch(
        "custom_components.homestral.conversation.conversation.async_get_result_from_chat_log",
        return_value=MagicMock(),
    ) as result_helper:
        await entity._async_handle_message(user_input, chat_log)

    entity._runner.async_run_streaming.assert_awaited_once_with(chat_log, user_input)
    result_helper.assert_called_once_with(user_input, chat_log)


@pytest.mark.asyncio
async def test_handle_message_turns_runner_errors_into_a_chat_log_message():
    """Une erreur du runner devient un message d'erreur, jamais une exception."""
    entity = _build_entity()
    entity._runner.async_run_streaming = AsyncMock(side_effect=RuntimeError("API down"))
    chat_log = FakeChatLog(FakeLLMApi())

    with patch(
        "custom_components.homestral.conversation.conversation.async_get_result_from_chat_log",
        return_value=MagicMock(),
    ):
        await entity._async_handle_message(make_user_input("Bonjour"), chat_log)

    # Internal error details are NOT leaked — only a generic message in the chat log.
    assert "Désolé, une erreur est survenue" in chat_log.content[-1].content
    assert "API down" not in chat_log.content[-1].content


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
