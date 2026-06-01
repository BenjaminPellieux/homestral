"""
Tests for HAToolExecutor device control via control_ha_device FunctionTool.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_control_ha_device_turn_on_light():
    """HAToolExecutor routes control_ha_device to DeviceController."""
    from homestral.tools import HAToolExecutor

    mock_hass = MagicMock()
    with patch("homestral.tools.DeviceController") as mock_dc_class:
        mock_dc = AsyncMock()
        mock_dc_class.return_value = mock_dc
        mock_dc.control_device.return_value = {
            "success": True,
            "entity_id": "light.salon",
            "command": "turn_on",
            "parameters": {},
        }

        executor = HAToolExecutor(mock_hass)
        raw = await executor.execute(
            "control_ha_device",
            {"entity_id": "light.salon", "command": "turn_on"},
        )

        result = json.loads(raw)
        assert result["success"] is True
        assert result["entity_id"] == "light.salon"
        mock_dc.control_device.assert_called_once_with("light.salon", "turn_on", {})


@pytest.mark.asyncio
async def test_control_ha_device_set_temperature():
    """HAToolExecutor passes temperature parameter to DeviceController."""
    from homestral.tools import HAToolExecutor

    mock_hass = MagicMock()
    with patch("homestral.tools.DeviceController") as mock_dc_class:
        mock_dc = AsyncMock()
        mock_dc_class.return_value = mock_dc
        mock_dc.control_device.return_value = {
            "success": True,
            "entity_id": "climate.chambre",
            "command": "set_temperature",
            "parameters": {"temperature": 20.0},
        }

        executor = HAToolExecutor(mock_hass)
        raw = await executor.execute(
            "control_ha_device",
            {
                "entity_id": "climate.chambre",
                "command": "set_temperature",
                "parameters": {"temperature": 20.0},
            },
        )

        result = json.loads(raw)
        assert result["success"] is True
        mock_dc.control_device.assert_called_once_with(
            "climate.chambre", "set_temperature", {"temperature": 20.0}
        )


@pytest.mark.asyncio
async def test_control_ha_device_missing_parameters_defaults_to_empty():
    """parameters key is optional — executor passes {} when absent."""
    from homestral.tools import HAToolExecutor

    mock_hass = MagicMock()
    with patch("homestral.tools.DeviceController") as mock_dc_class:
        mock_dc = AsyncMock()
        mock_dc_class.return_value = mock_dc
        mock_dc.control_device.return_value = {"success": True, "entity_id": "switch.prise", "command": "turn_off"}

        executor = HAToolExecutor(mock_hass)
        await executor.execute("control_ha_device", {"entity_id": "switch.prise", "command": "turn_off"})

        mock_dc.control_device.assert_called_once_with("switch.prise", "turn_off", {})


@pytest.mark.asyncio
async def test_control_ha_device_api_error_returns_error_json():
    """DeviceController exception is caught and returned as JSON error."""
    from homestral.tools import HAToolExecutor

    mock_hass = MagicMock()
    with patch("homestral.tools.DeviceController") as mock_dc_class:
        mock_dc = AsyncMock()
        mock_dc_class.return_value = mock_dc
        mock_dc.control_device.side_effect = RuntimeError("HA unavailable")

        executor = HAToolExecutor(mock_hass)
        raw = await executor.execute("control_ha_device", {"entity_id": "light.x", "command": "turn_on"})

        result = json.loads(raw)
        assert "error" in result


def test_list_ha_entities_truncation_note():
    """_list_ha_entities adds a note when more than 30 entities exist."""
    from homestral.tools import HAToolExecutor

    mock_hass = MagicMock()
    fake_states = []
    for i in range(35):
        s = MagicMock()
        s.entity_id = f"light.lamp_{i}"
        s.state = "off"
        s.attributes = {"friendly_name": f"Lamp {i}"}
        fake_states.append(s)
    mock_hass.states.async_all.return_value = fake_states

    executor = HAToolExecutor(mock_hass)
    result = executor._list_ha_entities("light")

    assert len(result["entities"]) == 30
    assert result["total"] == 35
    assert result["truncated"] is True
    assert "note" in result
    assert "35" in result["note"]


def test_list_ha_entities_no_note_when_under_limit():
    """No note field when entity count is within the 30-entity limit."""
    from homestral.tools import HAToolExecutor

    mock_hass = MagicMock()
    fake_states = []
    for i in range(10):
        s = MagicMock()
        s.entity_id = f"light.lamp_{i}"
        s.state = "on"
        s.attributes = {}
        fake_states.append(s)
    mock_hass.states.async_all.return_value = fake_states

    executor = HAToolExecutor(mock_hass)
    result = executor._list_ha_entities("light")

    assert len(result["entities"]) == 10
    assert result["truncated"] is False
    assert "note" not in result


if __name__ == "__main__":
    pytest.main([__file__])
