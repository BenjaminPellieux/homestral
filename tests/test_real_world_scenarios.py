"""
Tests for real-world scenarios with natural language device control.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homestral.conversation import MistralConversationEntity
from homestral.api_control import DeviceController
from homestral.errors import ConversationError


@pytest.mark.asyncio
@patch('homestral.conversation.DeviceController')
async def test_turn_on_living_room_light(mock_device_controller):
    """Test turning on living room light with natural language command."""
    # Setup mocks
    mock_controller_instance = MagicMock()
    mock_device_controller.return_value = mock_controller_instance
    
    # Mock device info response
    mock_controller_instance.get_device_info.return_value = {
        'type': 'entity',
        'entity_id': 'light.living_room_light',
        'name': 'Living Room Light',
        'platform': 'light',
        'capabilities': {
            'state': 'off',
            'attributes': ['brightness', 'color_temp'],
            'supported_commands': ['turn_on', 'turn_off', 'set_brightness']
        }
    }
    
    # Mock control response
    mock_controller_instance.control_device.return_value = {
        'success': True,
        'entity_id': 'light.living_room_light',
        'command': 'turn_on',
        'parameters': {}
    }
    
    # Create conversation entity
    entity = MistralConversationEntity(None, MagicMock())
    
    # Create chat log mock
    chat_log = MagicMock()
    chat_log.content = []
    
    # Create user input
    user_input = MagicMock()
    user_input.text = "Allume la lumière du salon"
    
    # Call the message handler
    result = await entity._async_handle_message(user_input, chat_log)
    
    # Verify device control was called
    mock_controller_instance.get_device_info.assert_called_once_with("light.living_room_light")
    mock_controller_instance.control_device.assert_called_once_with(
        "light.living_room_light", "turn_on", {}
    )
    
    # Verify response was added to chat log
    assert len(chat_log.content) == 1
    assert "Successfully turn_on light.living_room_light" in chat_log.content[0].content


@pytest.mark.asyncio
@patch('homestral.conversation.DeviceController')
async def test_set_thermostat_temperature(mock_device_controller):
    """Test setting thermostat temperature with natural language."""
    # Setup mocks
    mock_controller_instance = MagicMock()
    mock_device_controller.return_value = mock_controller_instance
    
    # Mock device info response
    mock_controller_instance.get_device_info.return_value = {
        'type': 'entity',
        'entity_id': 'climate.thermostat',
        'name': 'Thermostat',
        'platform': 'climate',
        'capabilities': {
            'state': 'heat',
            'attributes': ['temperature', 'hvac_mode'],
            'supported_commands': ['set_temperature', 'set_hvac_mode']
        }
    }
    
    # Mock control response
    mock_controller_instance.control_device.return_value = {
        'success': True,
        'entity_id': 'climate.thermostat',
        'command': 'set_temperature',
        'parameters': {'temperature': 22.0}
    }
    
    # Create conversation entity
    entity = MistralConversationEntity(None, MagicMock())
    
    # Create chat log mock
    chat_log = MagicMock()
    chat_log.content = []
    
    # Create user input
    user_input = MagicMock()
    user_input.text = "Règle la température à 22 degrés"
    
    # Call the message handler
    result = await entity._async_handle_message(user_input, chat_log)
    
    # Verify device control was called with correct parameters
    mock_controller_instance.control_device.assert_called_once()
    call_args = mock_controller_instance.control_device.call_args[0]
    assert call_args[0] == "climate.thermostat"
    assert call_args[1] == "set_temperature"
    assert call_args[2]['temperature'] == 22.0
    
    # Verify success response
    assert len(chat_log.content) == 1
    assert "Successfully set_temperature climate.thermostat" in chat_log.content[0].content


@pytest.mark.asyncio
@patch('homestral.conversation.DeviceController')
async def test_turn_off_all_switches(mock_device_controller):
    """Test turning off all switches command."""
    # Setup mocks
    mock_controller_instance = MagicMock()
    mock_device_controller.return_value = mock_controller_instance
    
    # Mock device info response for switch
    mock_controller_instance.get_device_info.return_value = {
        'type': 'entity',
        'entity_id': 'switch.all_switches',
        'name': 'All Switches',
        'platform': 'switch',
        'capabilities': {
            'state': 'on',
            'attributes': [],
            'supported_commands': ['turn_on', 'turn_off', 'toggle']
        }
    }
    
    # Mock control response
    mock_controller_instance.control_device.return_value = {
        'success': True,
        'entity_id': 'switch.all_switches',
        'command': 'turn_off',
        'parameters': {}
    }
    
    # Create conversation entity
    entity = MistralConversationEntity(None, MagicMock())
    
    # Create chat log mock
    chat_log = MagicMock()
    chat_log.content = []
    
    # Create user input
    user_input = MagicMock()
    user_input.text = "Éteins toutes les prises"
    
    # Call the message handler
    result = await entity._async_handle_message(user_input, chat_log)
    
    # Verify device control was called
    mock_controller_instance.control_device.assert_called_once_with(
        "switch.all_switches", "turn_off", {}
    )
    
    # Verify response
    assert len(chat_log.content) == 1
    assert "Successfully turn_off switch.all_switches" in chat_log.content[0].content


@pytest.mark.asyncio
@patch('homestral.conversation.DeviceController')
async def test_open_garage_door(mock_device_controller):
    """Test opening garage door with natural language."""
    # Setup mocks
    mock_controller_instance = MagicMock()
    mock_device_controller.return_value = mock_controller_instance
    
    # Mock device info response
    mock_controller_instance.get_device_info.return_value = {
        'type': 'entity',
        'entity_id': 'cover.garage_door',
        'name': 'Garage Door',
        'platform': 'cover',
        'capabilities': {
            'state': 'closed',
            'attributes': ['position'],
            'supported_commands': ['open', 'close', 'stop', 'set_position']
        }
    }
    
    # Mock control response
    mock_controller_instance.control_device.return_value = {
        'success': True,
        'entity_id': 'cover.garage_door',
        'command': 'open',
        'parameters': {}
    }
    
    # Create conversation entity
    entity = MistralConversationEntity(None, MagicMock())
    
    # Create chat log mock
    chat_log = MagicMock()
    chat_log.content = []
    
    # Create user input
    user_input = MagicMock()
    user_input.text = "Ouvre la porte du garage"
    
    # Call the message handler
    result = await entity._async_handle_message(user_input, chat_log)
    
    # Verify device control was called
    mock_controller_instance.control_device.assert_called_once_with(
        "cover.garage_door", "open", {}
    )
    
    # Verify response
    assert len(chat_log.content) == 1
    assert "Successfully open cover.garage_door" in chat_log.content[0].content


@pytest.mark.asyncio
@patch('homestral.conversation.DeviceController')
async def test_device_not_found_error(mock_device_controller):
    """Test handling of device not found error."""
    # Setup mocks
    mock_controller_instance = MagicMock()
    mock_device_controller.return_value = mock_controller_instance
    
    # Mock device info to raise error
    from homestral.errors import ConfigurationError
    mock_controller_instance.get_device_info.side_effect = ConfigurationError(
        message="Device/Entity not found: unknown_device",
        code="DEVICE_NOT_FOUND",
        details={"device_id": "unknown_device"}
    )
    
    # Create conversation entity
    entity = MistralConversationEntity(None, MagicMock())
    
    # Create chat log mock
    chat_log = MagicMock()
    chat_log.content = []
    
    # Create user input
    user_input = MagicMock()
    user_input.text = "Allume l'appareil inconnu"
    
    # Call the message handler
    result = await entity._async_handle_message(user_input, chat_log)
    
    # Verify error response
    assert len(chat_log.content) == 1
    assert "I couldn't identify the device" in chat_log.content[0].content


@pytest.mark.asyncio
@patch('homestral.conversation.DeviceController')
async def test_unsupported_command_error(mock_device_controller):
    """Test handling of unsupported command error."""
    # Setup mocks
    mock_controller_instance = MagicMock()
    mock_device_controller.return_value = mock_controller_instance
    
    # Mock device info response
    mock_controller_instance.get_device_info.return_value = {
        'type': 'entity',
        'entity_id': 'sensor.temperature',
        'name': 'Temperature Sensor',
        'platform': 'sensor',
        'capabilities': {
            'state': '22.5',
            'attributes': ['unit_of_measurement'],
            'supported_commands': []  # Sensors typically don't support commands
        }
    }
    
    # Mock control to raise error
    from homestral.errors import ConfigurationError
    mock_controller_instance.control_device.side_effect = ConfigurationError(
        message="Unsupported domain: sensor",
        code="UNSUPPORTED_DOMAIN",
        details={"domain": "sensor", "entity_id": "sensor.temperature"}
    )
    
    # Create conversation entity
    entity = MistralConversationEntity(None, MagicMock())
    
    # Create chat log mock
    chat_log = MagicMock()
    chat_log.content = []
    
    # Create user input
    user_input = MagicMock()
    user_input.text = "Allume le capteur de température"
    
    # Call the message handler
    result = await entity._async_handle_message(user_input, chat_log)
    
    # Verify error response
    assert len(chat_log.content) == 1
    assert "Sorry, I encountered an error" in chat_log.content[0].content


@pytest.mark.asyncio
@patch('homestral.conversation.DeviceController')
async def test_non_device_command_passthrough(mock_device_controller):
    """Test that non-device commands are passed through to Mistral AI."""
    # Setup mocks
    mock_controller_instance = MagicMock()
    mock_device_controller.return_value = mock_controller_instance
    
    # Create conversation entity
    entity = MistralConversationEntity(None, MagicMock())
    
    # Mock the Mistral client
    mock_client = MagicMock()
    mock_conversation_response = MagicMock()
    mock_conversation_response.conversation_id = "test_conversation_123"
    
    # Mock outputs
    mock_message_entry = MagicMock()
    mock_message_entry.content = "Hello! How can I help you today?"
    mock_conversation_response.outputs = [mock_message_entry]
    
    mock_client.beta.conversations.start.return_value = mock_conversation_response
    entity._client = mock_client
    
    # Create chat log mock
    chat_log = MagicMock()
    chat_log.content = []
    
    # Create user input (non-device command)
    user_input = MagicMock()
    user_input.text = "What's the weather today?"
    
    # Call the message handler
    result = await entity._async_handle_message(user_input, chat_log)
    
    # Verify that device control was NOT called
    mock_controller_instance.get_device_info.assert_not_called()
    mock_controller_instance.control_device.assert_not_called()
    
    # Verify that Mistral conversation was called instead
    mock_client.beta.conversations.start.assert_called_once()
    
    # Verify response from Mistral was added to chat log
    assert len(chat_log.content) == 1
    assert "Hello! How can I help you today?" in chat_log.content[0].content


if __name__ == "__main__":
    pytest.main([__file__])
