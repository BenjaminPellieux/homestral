"""
Module for controlling Home Assistant devices via Mistral API.
"""

from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, HomeAssistantError, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SERVICE_CONTROL_DEVICE
from .errors import APIError, ConfigurationError
from .logging_config import get_logger
from .safety import guard

_LOGGER = get_logger(__name__)

# Commands accepted by the control_device service, per domain.
_ALLOWED_COMMANDS = frozenset(
    {
        "turn_on",
        "turn_off",
        "toggle",
        "open",
        "close",
        "stop",
        "set_position",
        "set_temperature",
        "set_hvac_mode",
        "play",
        "pause",
        "volume_up",
        "volume_down",
        "set_volume",
        "lock",
        "unlock",
        "set_speed",
        "oscillate",
        "start",
        "return_to_base",
        "clean_spot",
    }
)

CONTROL_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("command"): vol.In(sorted(_ALLOWED_COMMANDS)),
        vol.Optional("parameters"): dict,
    }
)


class DeviceController:
    """Class to control Home Assistant devices."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the device controller."""
        self.hass = hass
        self.entity_registry = er.async_get(hass)
        self.device_registry = dr.async_get(hass)

    async def get_device_info(self, device_id: str) -> dict[str, Any]:
        """Get information about a specific device."""
        try:
            # Check if it's an entity ID
            if device_id.startswith(
                ("light.", "switch.", "sensor.", "climate.", "cover.", "media_player.", "lock.", "fan.", "vacuum.")
            ):
                entity_entry = self.entity_registry.async_get(device_id)
                if entity_entry:
                    return {
                        "type": "entity",
                        "entity_id": device_id,
                        "device_id": entity_entry.device_id,
                        "name": entity_entry.name,
                        "platform": entity_entry.platform,
                        "capabilities": self._get_entity_capabilities(device_id),
                    }

            # Check if it's a device ID
            device_entry = self.device_registry.async_get(device_id)
            if device_entry:
                return {
                    "type": "device",
                    "device_id": device_id,
                    "name": device_entry.name,
                    "manufacturer": device_entry.manufacturer,
                    "model": device_entry.model,
                    "entities": list(device_entry.config_entries),
                }

            raise ConfigurationError(
                message=f"Device/Entity not found: {device_id}",
                code="DEVICE_NOT_FOUND",
                details={"device_id": device_id},
            )

        except Exception as e:
            error = APIError(
                message=f"Error getting device info: {e}",
                code="DEVICE_INFO_ERROR",
                details={"device_id": device_id, "error": str(e)},
            )
            _LOGGER.error(f"Error getting device info: {error}")
            raise error from e

    def _get_entity_capabilities(self, entity_id: str) -> dict[str, Any]:
        """Get capabilities for a specific entity."""
        state = self.hass.states.get(entity_id)
        if not state:
            return {}

        capabilities = {"state": state.state, "attributes": list(state.attributes.keys()), "supported_commands": []}

        # Determine supported commands based on domain
        domain = entity_id.split(".")[0]
        if domain == "light":
            capabilities["supported_commands"] = [
                "turn_on",
                "turn_off",
                "toggle",
                "set_brightness",
                "set_color",
                "set_color_temp",
            ]
        elif domain == "switch":
            capabilities["supported_commands"] = ["turn_on", "turn_off", "toggle"]
        elif domain == "climate":
            capabilities["supported_commands"] = ["set_temperature", "set_hvac_mode", "turn_on", "turn_off"]
        elif domain == "cover":
            capabilities["supported_commands"] = ["open", "close", "stop", "set_position"]
        elif domain == "media_player":
            capabilities["supported_commands"] = [
                "turn_on",
                "turn_off",
                "volume_up",
                "volume_down",
                "set_volume",
                "play",
                "pause",
                "stop",
            ]
        elif domain == "lock":
            capabilities["supported_commands"] = ["lock", "unlock"]
        elif domain == "fan":
            capabilities["supported_commands"] = ["turn_on", "turn_off", "set_speed", "oscillate"]
        elif domain == "vacuum":
            capabilities["supported_commands"] = ["start", "stop", "pause", "return_to_base", "clean_spot"]

        return capabilities

    async def control_device(
        self, device_id: str, command: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Control a device with the specified command and parameters."""
        try:
            _LOGGER.debug(f"Controlling device {device_id} with command {command}")

            # Get device info first
            device_info = await self.get_device_info(device_id)

            if device_info["type"] == "entity":
                entity_id = device_info["entity_id"]
                domain = entity_id.split(".")[0]

                # Handle different domains
                if domain == "light":
                    return await self._control_light(entity_id, command, parameters or {})
                elif domain == "switch":
                    return await self._control_switch(entity_id, command, parameters or {})
                elif domain == "climate":
                    return await self._control_climate(entity_id, command, parameters or {})
                elif domain == "cover":
                    return await self._control_cover(entity_id, command, parameters or {})
                elif domain == "media_player":
                    return await self._control_media_player(entity_id, command, parameters or {})
                elif domain == "lock":
                    return await self._control_lock(entity_id, command, parameters or {})
                elif domain == "fan":
                    return await self._control_fan(entity_id, command, parameters or {})
                elif domain == "vacuum":
                    return await self._control_vacuum(entity_id, command, parameters or {})
                else:
                    raise ConfigurationError(
                        message=f"Unsupported domain: {domain}",
                        code="UNSUPPORTED_DOMAIN",
                        details={"domain": domain, "entity_id": entity_id},
                    )
            else:
                raise ConfigurationError(
                    message="Can only control entities directly, not devices",
                    code="DEVICE_CONTROL_NOT_SUPPORTED",
                    details={"device_id": device_id},
                )

        except Exception as e:
            error = APIError(
                message=f"Error controlling device: {e}",
                code="DEVICE_CONTROL_ERROR",
                details={"device_id": device_id, "command": command, "parameters": parameters, "error": str(e)},
            )
            _LOGGER.error(f"Error controlling device: {error}")
            raise error from e

    async def _control_light(self, entity_id: str, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Control a light entity."""
        service_data = {"entity_id": entity_id}

        if command == "turn_on":
            if "brightness" in parameters:
                service_data["brightness"] = parameters["brightness"]
            if "color_temp" in parameters:
                service_data["color_temp"] = parameters["color_temp"]
            if "rgb_color" in parameters:
                service_data["rgb_color"] = parameters["rgb_color"]
            await self.hass.services.async_call("light", "turn_on", service_data)
        elif command == "turn_off":
            await self.hass.services.async_call("light", "turn_off", service_data)
        elif command == "toggle":
            await self.hass.services.async_call("light", "toggle", service_data)
        else:
            raise ConfigurationError(
                message=f"Unsupported command for light: {command}",
                code="UNSUPPORTED_COMMAND",
                details={"entity_id": entity_id, "command": command},
            )

        return {"success": True, "entity_id": entity_id, "command": command, "parameters": parameters}

    async def _control_switch(self, entity_id: str, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Control a switch entity."""
        service_data = {"entity_id": entity_id}

        if command == "turn_on":
            await self.hass.services.async_call("switch", "turn_on", service_data)
        elif command == "turn_off":
            await self.hass.services.async_call("switch", "turn_off", service_data)
        elif command == "toggle":
            await self.hass.services.async_call("switch", "toggle", service_data)
        else:
            raise ConfigurationError(
                message=f"Unsupported command for switch: {command}",
                code="UNSUPPORTED_COMMAND",
                details={"entity_id": entity_id, "command": command},
            )

        return {"success": True, "entity_id": entity_id, "command": command}

    async def _control_climate(self, entity_id: str, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Control a climate entity."""
        service_data = {"entity_id": entity_id}

        if command == "set_temperature":
            if "temperature" not in parameters:
                raise ConfigurationError(
                    message="Temperature parameter required for set_temperature command",
                    code="MISSING_PARAMETER",
                    details={"entity_id": entity_id, "command": command, "required_parameter": "temperature"},
                )
            service_data["temperature"] = parameters["temperature"]
            await self.hass.services.async_call("climate", "set_temperature", service_data)
        elif command == "set_hvac_mode":
            if "hvac_mode" not in parameters:
                raise ConfigurationError(
                    message="HVAC mode parameter required for set_hvac_mode command",
                    code="MISSING_PARAMETER",
                    details={"entity_id": entity_id, "command": command, "required_parameter": "hvac_mode"},
                )
            service_data["hvac_mode"] = parameters["hvac_mode"]
            await self.hass.services.async_call("climate", "set_hvac_mode", service_data)
        elif command == "turn_on":
            await self.hass.services.async_call("climate", "turn_on", service_data)
        elif command == "turn_off":
            await self.hass.services.async_call("climate", "turn_off", service_data)
        else:
            raise ConfigurationError(
                message=f"Unsupported command for climate: {command}",
                code="UNSUPPORTED_COMMAND",
                details={"entity_id": entity_id, "command": command},
            )

        return {"success": True, "entity_id": entity_id, "command": command, "parameters": parameters}

    # Add more control methods for other domains as needed...

    async def _control_cover(self, entity_id: str, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Control a cover entity."""
        service_data = {"entity_id": entity_id}

        if command == "open":
            await self.hass.services.async_call("cover", "open_cover", service_data)
        elif command == "close":
            await self.hass.services.async_call("cover", "close_cover", service_data)
        elif command == "stop":
            await self.hass.services.async_call("cover", "stop_cover", service_data)
        elif command == "set_position":
            if "position" not in parameters:
                raise ConfigurationError(
                    message="Position parameter required for set_position command",
                    code="MISSING_PARAMETER",
                    details={"entity_id": entity_id, "command": command, "required_parameter": "position"},
                )
            service_data["position"] = parameters["position"]
            await self.hass.services.async_call("cover", "set_cover_position", service_data)
        else:
            raise ConfigurationError(
                message=f"Unsupported command for cover: {command}",
                code="UNSUPPORTED_COMMAND",
                details={"entity_id": entity_id, "command": command},
            )

        return {"success": True, "entity_id": entity_id, "command": command, "parameters": parameters}

    async def _control_media_player(self, entity_id: str, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Control a media player entity."""
        service_data = {"entity_id": entity_id}

        if command == "turn_on":
            await self.hass.services.async_call("media_player", "turn_on", service_data)
        elif command == "turn_off":
            await self.hass.services.async_call("media_player", "turn_off", service_data)
        elif command == "volume_up":
            await self.hass.services.async_call("media_player", "volume_up", service_data)
        elif command == "volume_down":
            await self.hass.services.async_call("media_player", "volume_down", service_data)
        elif command == "set_volume":
            if "volume_level" not in parameters:
                raise ConfigurationError(
                    message="Volume level parameter required for set_volume command",
                    code="MISSING_PARAMETER",
                    details={"entity_id": entity_id, "command": command, "required_parameter": "volume_level"},
                )
            service_data["volume_level"] = parameters["volume_level"]
            await self.hass.services.async_call("media_player", "volume_set", service_data)
        elif command == "play":
            await self.hass.services.async_call("media_player", "media_play", service_data)
        elif command == "pause":
            await self.hass.services.async_call("media_player", "media_pause", service_data)
        elif command == "stop":
            await self.hass.services.async_call("media_player", "media_stop", service_data)
        else:
            raise ConfigurationError(
                message=f"Unsupported command for media_player: {command}",
                code="UNSUPPORTED_COMMAND",
                details={"entity_id": entity_id, "command": command},
            )

        return {"success": True, "entity_id": entity_id, "command": command, "parameters": parameters}

    async def _control_lock(self, entity_id: str, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Control a lock entity."""
        service_data = {"entity_id": entity_id}

        if command == "lock":
            await self.hass.services.async_call("lock", "lock", service_data)
        elif command == "unlock":
            await self.hass.services.async_call("lock", "unlock", service_data)
        else:
            raise ConfigurationError(
                message=f"Unsupported command for lock: {command}",
                code="UNSUPPORTED_COMMAND",
                details={"entity_id": entity_id, "command": command},
            )

        return {"success": True, "entity_id": entity_id, "command": command}

    async def _control_fan(self, entity_id: str, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Control a fan entity."""
        service_data = {"entity_id": entity_id}

        if command == "turn_on":
            await self.hass.services.async_call("fan", "turn_on", service_data)
        elif command == "turn_off":
            await self.hass.services.async_call("fan", "turn_off", service_data)
        elif command == "set_speed":
            if "speed" not in parameters:
                raise ConfigurationError(
                    message="Speed parameter required for set_speed command",
                    code="MISSING_PARAMETER",
                    details={"entity_id": entity_id, "command": command, "required_parameter": "speed"},
                )
            service_data["speed"] = parameters["speed"]
            await self.hass.services.async_call("fan", "set_speed", service_data)
        elif command == "oscillate":
            if "oscillating" not in parameters:
                raise ConfigurationError(
                    message="Oscillating parameter required for oscillate command",
                    code="MISSING_PARAMETER",
                    details={"entity_id": entity_id, "command": command, "required_parameter": "oscillating"},
                )
            service_data["oscillating"] = parameters["oscillating"]
            await self.hass.services.async_call("fan", "oscillate", service_data)
        else:
            raise ConfigurationError(
                message=f"Unsupported command for fan: {command}",
                code="UNSUPPORTED_COMMAND",
                details={"entity_id": entity_id, "command": command},
            )

        return {"success": True, "entity_id": entity_id, "command": command, "parameters": parameters}

    async def _control_vacuum(self, entity_id: str, command: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Control a vacuum entity."""
        service_data = {"entity_id": entity_id}

        if command == "start":
            await self.hass.services.async_call("vacuum", "start", service_data)
        elif command == "stop":
            await self.hass.services.async_call("vacuum", "stop", service_data)
        elif command == "pause":
            await self.hass.services.async_call("vacuum", "pause", service_data)
        elif command == "return_to_base":
            await self.hass.services.async_call("vacuum", "return_to_base", service_data)
        elif command == "clean_spot":
            await self.hass.services.async_call("vacuum", "clean_spot", service_data)
        else:
            raise ConfigurationError(
                message=f"Unsupported command for vacuum: {command}",
                code="UNSUPPORTED_COMMAND",
                details={"entity_id": entity_id, "command": command},
            )

        return {"success": True, "entity_id": entity_id, "command": command}


async def async_setup_api_control(hass: HomeAssistant) -> DeviceController:
    """Set up the API control service."""
    controller = DeviceController(hass)

    async def handle_control_device_service(call: ServiceCall) -> None:
        """Handle the control_device service call — admin-only, guarded."""
        # Only an authenticated admin user may call this service.
        context = call.context
        user = await hass.auth.async_get_user(context.user_id) if context.user_id else None
        if user is None or not user.is_admin:
            raise HomeAssistantError("homestral.control_device requires an admin user")

        device_id: str = call.data["device_id"]
        command: str = call.data["command"]
        parameters: dict = call.data.get("parameters", {})

        # Apply the sensitive-action guard (lock, alarm, cover).
        refusal = guard(
            "control_ha_device",
            {"entity_id": device_id, "command": command},
            chat_log=None,
            enabled=True,
        )
        if refusal is not None:
            raise HomeAssistantError(refusal["error"])

        try:
            result = await controller.control_device(device_id, command, parameters)
            _LOGGER.info(f"Successfully controlled device: {result}")
        except Exception as e:
            _LOGGER.error(f"Error in control_device service: {e}")
            raise HomeAssistantError("Failed to control device") from e

    # Register the service with a schema — HA validates call.data against it.
    hass.services.async_register(
        DOMAIN, SERVICE_CONTROL_DEVICE, handle_control_device_service, schema=CONTROL_DEVICE_SCHEMA
    )

    return controller
