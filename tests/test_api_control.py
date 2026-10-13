"""
Tests unitaires pour le module api_control.py.

DeviceController recupere les registres via
``homeassistant.helpers.entity_registry.async_get(hass)`` et
``homeassistant.helpers.device_registry.async_get(hass)`` — on patch donc
``homestral.api_control.er.async_get`` / ``homestral.api_control.dr.async_get``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.homestral.api_control import DeviceController
from custom_components.homestral.errors import APIError


def _make_controller(mock_hass, entity_registry=None, device_registry=None):
    """Instancie un DeviceController avec des registres mockes."""
    with (
        patch("custom_components.homestral.api_control.er.async_get", return_value=entity_registry),
        patch("custom_components.homestral.api_control.dr.async_get", return_value=device_registry),
    ):
        return DeviceController(mock_hass)


def _make_entity_entry(device_id="test_device", name="Test Light", platform="light"):
    entry = MagicMock()
    entry.device_id = device_id
    entry.name = name
    entry.platform = platform
    return entry


def _make_device_entry(name="Test Device"):
    entry = MagicMock()
    entry.name = name
    entry.manufacturer = "Test Manufacturer"
    entry.model = "Test Model"
    entry.config_entries = ["test_entry"]
    return entry


@pytest.mark.asyncio
async def test_get_device_info_entity():
    """Test getting device info for an entity."""
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    mock_device_registry = MagicMock()

    mock_entity_registry.async_get.return_value = _make_entity_entry()

    mock_state = MagicMock()
    mock_state.state = "on"
    mock_state.attributes = {"brightness": 255, "color_temp": 400}
    mock_hass.states.get.return_value = mock_state

    controller = _make_controller(mock_hass, mock_entity_registry, mock_device_registry)

    result = await controller.get_device_info("light.test_light")

    assert result["type"] == "entity"
    assert result["entity_id"] == "light.test_light"
    assert result["device_id"] == "test_device"
    assert result["name"] == "Test Light"
    assert result["platform"] == "light"
    assert result["capabilities"]["state"] == "on"
    assert set(result["capabilities"]["attributes"]) == {"brightness", "color_temp"}
    assert "turn_on" in result["capabilities"]["supported_commands"]


@pytest.mark.asyncio
async def test_get_device_info_device():
    """Test getting device info for a device (id not prefixed by a domain)."""
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    mock_device_registry = MagicMock()

    mock_entity_registry.async_get.return_value = None
    mock_device_registry.async_get.return_value = _make_device_entry()

    controller = _make_controller(mock_hass, mock_entity_registry, mock_device_registry)

    result = await controller.get_device_info("test_device_id")

    assert result["type"] == "device"
    assert result["device_id"] == "test_device_id"
    assert result["name"] == "Test Device"
    assert result["manufacturer"] == "Test Manufacturer"
    assert result["model"] == "Test Model"
    assert result["entities"] == ["test_entry"]


@pytest.mark.asyncio
async def test_get_device_info_not_found():
    """Test getting device info for a non-existent device."""
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    mock_device_registry = MagicMock()

    # Aucun registre ne connait cet id
    mock_entity_registry.async_get.return_value = None
    mock_device_registry.async_get.return_value = None

    controller = _make_controller(mock_hass, mock_entity_registry, mock_device_registry)

    with pytest.raises(APIError) as exc_info:
        await controller.get_device_info("non_existent_device")

    assert "Device/Entity not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_control_light():
    """Test controlling a light entity."""
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    mock_entity_registry.async_get.return_value = _make_entity_entry()

    mock_state = MagicMock()
    mock_state.state = "on"
    mock_state.attributes = {}
    mock_hass.states.get.return_value = mock_state

    mock_service_call = AsyncMock()
    mock_hass.services.async_call = mock_service_call

    controller = _make_controller(mock_hass, mock_entity_registry, MagicMock())

    result = await controller.control_device("light.test_light", "turn_on", {})

    mock_service_call.assert_called_once_with("light", "turn_on", {"entity_id": "light.test_light"})
    assert result["success"] is True
    assert result["entity_id"] == "light.test_light"
    assert result["command"] == "turn_on"


@pytest.mark.asyncio
async def test_control_device_unsupported_domain():
    """Test controlling a device with unsupported domain."""
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    mock_entity_registry.async_get.return_value = _make_entity_entry(name="Test Sensor", platform="sensor")

    mock_state = MagicMock()
    mock_state.state = "on"
    mock_state.attributes = {}
    mock_hass.states.get.return_value = mock_state

    controller = _make_controller(mock_hass, mock_entity_registry, MagicMock())

    with pytest.raises(APIError) as exc_info:
        await controller.control_device("sensor.test_sensor", "turn_on", {})

    assert "Unsupported domain" in str(exc_info.value)


@pytest.mark.asyncio
async def test_control_device_missing_parameter():
    """Test controlling a device with missing required parameter."""
    mock_hass = MagicMock()
    mock_entity_registry = MagicMock()
    mock_entity_registry.async_get.return_value = _make_entity_entry(name="Test Climate", platform="climate")

    mock_state = MagicMock()
    mock_state.state = "on"
    mock_state.attributes = {}
    mock_hass.states.get.return_value = mock_state

    controller = _make_controller(mock_hass, mock_entity_registry, MagicMock())

    with pytest.raises(APIError) as exc_info:
        await controller.control_device("climate.test_climate", "set_temperature", {})

    assert "parameter required" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__])
