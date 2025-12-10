"""
Tests unitaires pour le module api_control.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homestral.api_control import DeviceController
from homestral.errors import APIError, ConfigurationError


@pytest.mark.asyncio
async def test_get_device_info_entity():
    """Test getting device info for an entity."""
    # Créer un mock pour HomeAssistant
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    mock_device_registry = MagicMock()
    
    # Configurer les mocks
    mock_entity_entry = MagicMock()
    mock_entity_entry.device_id = "test_device"
    mock_entity_entry.name = "Test Light"
    mock_entity_entry.platform = "light"
    mock_entity_registry.async_get.return_value = mock_entity_entry
    
    mock_state = MagicMock()
    mock_state.state = "on"
    mock_state.attributes = {"brightness": 255, "color_temp": 400}
    mock_hass.states.get.return_value = mock_state
    
    # Créer une instance de DeviceController
    with patch('homestral.api_control.EntityRegistry', return_value=mock_entity_registry), \
         patch('homestral.api_control.DeviceRegistry', return_value=mock_device_registry):
        controller = DeviceController(mock_hass)
        
        # Appeler la méthode get_device_info
        result = await controller.get_device_info("light.test_light")
        
        # Vérifier que le résultat est correct
        assert result['type'] == 'entity'
        assert result['entity_id'] == "light.test_light"
        assert result['name'] == "Test Light"
        assert result['platform'] == "light"
        assert 'capabilities' in result


@pytest.mark.asyncio
async def test_get_device_info_device():
    """Test getting device info for a device."""
    # Créer un mock pour HomeAssistant
    mock_hass = MagicMock()
    mock_device_registry = MagicMock()
    
    # Configurer les mocks
    mock_device_entry = MagicMock()
    mock_device_entry.name = "Test Device"
    mock_device_entry.manufacturer = "Test Manufacturer"
    mock_device_entry.model = "Test Model"
    mock_device_entry.config_entries = ["test_entry"]
    mock_device_registry.async_get.return_value = mock_device_entry
    
    # Créer une instance de DeviceController
    with patch('homestral.api_control.DeviceRegistry', return_value=mock_device_registry):
        controller = DeviceController(mock_hass)
        
        # Appeler la méthode get_device_info
        result = await controller.get_device_info("test_device_id")
        
        # Vérifier que le résultat est correct
        assert result['type'] == 'device'
        assert result['device_id'] == "test_device_id"
        assert result['name'] == "Test Device"
        assert result['manufacturer'] == "Test Manufacturer"


@pytest.mark.asyncio
async def test_get_device_info_not_found():
    """Test getting device info for a non-existent device."""
    # Créer un mock pour HomeAssistant
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    mock_device_registry = MagicMock()
    
    # Configurer les mocks pour retourner None
    mock_entity_registry.async_get.return_value = None
    mock_device_registry.async_get.return_value = None
    
    # Créer une instance de DeviceController
    with patch('homestral.api_control.EntityRegistry', return_value=mock_entity_registry), \
         patch('homestral.api_control.DeviceRegistry', return_value=mock_device_registry):
        controller = DeviceController(mock_hass)
        
        # Vérifier qu'une exception est levée (ConfigurationError ou APIError)
        with pytest.raises((ConfigurationError, APIError)) as exc_info:
            await controller.get_device_info("non_existent_device")
        
        # Vérifier que c'est bien une erreur de device non trouvé
        assert "Device/Entity not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_control_light():
    """Test controlling a light entity."""
    # Créer un mock pour HomeAssistant
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    
    # Configurer les mocks
    mock_entity_entry = MagicMock()
    mock_entity_entry.device_id = "test_device"
    mock_entity_entry.name = "Test Light"
    mock_entity_entry.platform = "light"
    mock_entity_registry.async_get.return_value = mock_entity_entry
    
    mock_state = MagicMock()
    mock_state.state = "on"
    mock_state.attributes = {}
    mock_hass.states.get.return_value = mock_state
    
    # Créer un mock async pour services.async_call
    mock_service_call = AsyncMock()
    mock_hass.services.async_call = mock_service_call
    
    # Créer une instance de DeviceController
    with patch('homestral.api_control.EntityRegistry', return_value=mock_entity_registry):
        controller = DeviceController(mock_hass)
        
        # Appeler la méthode control_device
        result = await controller.control_device("light.test_light", "turn_on", {})
        
        # Vérifier que le service a été appelé
        mock_service_call.assert_called_once_with('light', 'turn_on', {'entity_id': 'light.test_light'})
        
        # Vérifier que le résultat est correct
        assert result['success'] == True
        assert result['entity_id'] == "light.test_light"
        assert result['command'] == "turn_on"


@pytest.mark.asyncio
async def test_control_device_unsupported_domain():
    """Test controlling a device with unsupported domain."""
    # Créer un mock pour HomeAssistant
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    
    # Configurer les mocks
    mock_entity_entry = MagicMock()
    mock_entity_entry.device_id = "test_device"
    mock_entity_entry.name = "Test Sensor"
    mock_entity_entry.platform = "sensor"
    mock_entity_registry.async_get.return_value = mock_entity_entry
    
    mock_state = MagicMock()
    mock_state.state = "on"
    mock_state.attributes = {}
    mock_hass.states.get.return_value = mock_state
    
    # Créer une instance de DeviceController
    with patch('homestral.api_control.EntityRegistry', return_value=mock_entity_registry):
        controller = DeviceController(mock_hass)
        
        # Vérifier qu'une exception est levée (ConfigurationError ou APIError)
        with pytest.raises((ConfigurationError, APIError)) as exc_info:
            await controller.control_device("sensor.test_sensor", "turn_on", {})
        
        # Vérifier que c'est bien une erreur de domaine non supporté
        assert "Unsupported domain" in str(exc_info.value)


@pytest.mark.asyncio
async def test_control_device_missing_parameter():
    """Test controlling a device with missing required parameter."""
    # Créer un mock pour HomeAssistant
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    
    # Configurer les mocks
    mock_entity_entry = MagicMock()
    mock_entity_entry.device_id = "test_device"
    mock_entity_entry.name = "Test Climate"
    mock_entity_entry.platform = "climate"
    mock_entity_registry.async_get.return_value = mock_entity_entry
    
    mock_state = MagicMock()
    mock_state.state = "on"
    mock_state.attributes = {}
    mock_hass.states.get.return_value = mock_state
    
    # Créer une instance de DeviceController
    with patch('homestral.api_control.EntityRegistry', return_value=mock_entity_registry):
        controller = DeviceController(mock_hass)
        
        # Vérifier qu'une exception est levée (ConfigurationError ou APIError)
        with pytest.raises((ConfigurationError, APIError)) as exc_info:
            await controller.control_device("climate.test_climate", "set_temperature", {})
        
        # Vérifier que c'est bien une erreur de paramètre manquant
        assert "parameter required" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__])
