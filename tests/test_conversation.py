"""
Tests unitaires pour le module conversation.py.

conversation.py n'utilise plus de DeviceController : le controle des appareils
passe par HAToolExecutor (tools.py) via la boucle de tools Mistral. On teste
donc les parametres envoyes a ``client.beta.conversations.start_async``
(model, tools, instructions, agent_id) en patchant ``build_ha_context``.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import MATCH_ALL

from homestral.conversation import MistralConversationEntity
from homestral.const import CONF_AGENT_ID, CONF_MODEL, CONF_USE_AGENT, DEFAULT_CHAT_MODEL
from homestral.errors import ConversationError
from homestral.tools import ALL_TOOLS


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


if __name__ == "__main__":
    pytest.main([__file__])
