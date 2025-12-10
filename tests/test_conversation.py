"""
Tests unitaires pour le module conversation.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homestral.conversation import MistralConversationEntity
from homestral.errors import ConversationError


@pytest.mark.asyncio
@patch('homestral.conversation.DeviceController')
async def test_async_handle_error(mock_device_controller):
    """Test la gestion des erreurs."""
    # Configurer le mock pour DeviceController
    mock_device_controller_instance = MagicMock()
    mock_device_controller.return_value = mock_device_controller_instance
    
    # Créer une instance de MistralConversationEntity
    entity = MistralConversationEntity(None, MagicMock())
    
    # Créer un mock pour le chat log
    chat_log = MagicMock()
    chat_log.content = []
    
    # Créer une erreur mock
    error = ConversationError(
        message="Test error",
        code="TEST_ERROR",
        details={"key": "value"}
    )
    
    # Appeler la méthode async_handle_error
    await entity.async_handle_error(chat_log, error)
    
    # Vérifier que l'erreur a été ajoutée au chat log
    assert len(chat_log.content) == 1
    assert "Error: Test error" in chat_log.content[0].content
    assert "Code: TEST_ERROR" in chat_log.content[0].content
    assert "Details: {'key': 'value'}" in chat_log.content[0].content


@patch('homestral.conversation.DeviceController')
def test_supported_languages(mock_device_controller):
    """Test les langues supportées."""
    # Configurer le mock pour DeviceController
    mock_device_controller_instance = MagicMock()
    mock_device_controller.return_value = mock_device_controller_instance
    
    entity = MistralConversationEntity(None, MagicMock())
    from homeassistant.const import MATCH_ALL
    assert entity.supported_languages == MATCH_ALL


if __name__ == "__main__":
    pytest.main([__file__])