import json

from homeassistant.core import HomeAssistant

try:
    from mistralai.client.models import Function, FunctionTool, WebSearchTool
except ImportError:
    from mistralai.models import Function, FunctionTool, WebSearchTool

from .api_control import DeviceController
from .logging_config import get_logger

_LOGGER = get_logger(__name__)

# Attributes safe to send to the Mistral API — a whitelist to avoid leaking
# GPS coordinates, presence state, tokens or internal URLs that some
# integrations store in entity attributes.
_SAFE_ATTRIBUTES = frozenset(
    {
        "friendly_name",
        "unit_of_measurement",
        "device_class",
        "state_class",
        "icon",
        "supported_features",
        "temperature",
        "current_temperature",
        "humidity",
        "pressure",
        "brightness",
        "color_temp",
        "color_mode",
        "hvac_modes",
        "hvac_mode",
        "min_temp",
        "max_temp",
        "target_temp",
        "fan_modes",
        "swing_modes",
        "current_position",
        "current_volume",
        "media_title",
        "media_artist",
        "media_duration",
        "is_locked",
        "battery_level",
        "attribution",
        "assumed_state",
        "supported_color_modes",
        "effect_list",
        "speed_list",
        "percentage",
        "percentage_step",
        "preset_modes",
        "swing_mode",
        "fan_mode",
        "mode",
    }
)

# Domains whose state reveals location, presence or security posture —
# never exposed to the model, even via the legacy tools.
_BLOCKED_DOMAINS = frozenset({"person", "device_tracker", "zone", "camera", "alarm_control_panel", "input_button"})

# ---------------------------------------------------------------------------
# Built-in Mistral tools (server-side, no client execution needed)
# ---------------------------------------------------------------------------

WEB_SEARCH_TOOL = WebSearchTool()

# ---------------------------------------------------------------------------
# Custom HA FunctionTools (client-side execution via HAToolExecutor)
# ---------------------------------------------------------------------------

HA_FUNCTION_TOOLS = [
    FunctionTool(
        function=Function(
            name="get_ha_state",
            description=(
                "Obtenir l'état actuel d'une entité Home Assistant (lumière, thermostat, capteur, couverture, etc.)"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "ID de l'entité HA, ex: light.salon, climate.chambre, sensor.temperature",
                    }
                },
                "required": ["entity_id"],
            },
        )
    ),
    FunctionTool(
        function=Function(
            name="list_ha_entities",
            description="Lister les entités d'un domaine Home Assistant avec leur état actuel",
            parameters={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domaine HA: light, switch, climate, cover, media_player, sensor, weather, lock, fan",
                        "enum": [
                            "light",
                            "switch",
                            "climate",
                            "cover",
                            "media_player",
                            "sensor",
                            "weather",
                            "lock",
                            "fan",
                        ],
                    }
                },
                "required": ["domain"],
            },
        )
    ),
    FunctionTool(
        function=Function(
            name="get_ha_weather",
            description="Obtenir la météo locale depuis les entités météo de Home Assistant",
            parameters={"type": "object", "properties": {}, "required": []},
        )
    ),
    FunctionTool(
        function=Function(
            name="control_ha_device",
            description=(
                "Contrôler un appareil Home Assistant : allumer/éteindre des lumières, "
                "régler le thermostat, ouvrir/fermer des volets, contrôler un lecteur média, etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "ID de l'entité HA, ex: light.salon, climate.chambre, cover.volet_salon",
                    },
                    "command": {
                        "type": "string",
                        "description": (
                            "Commande à exécuter. "
                            "Lumières: turn_on, turn_off, toggle. "
                            "Stores/volets: open, close, stop, set_position. "
                            "Thermostats: set_temperature, set_hvac_mode, turn_on, turn_off. "
                            "Prises/interrupteurs: turn_on, turn_off, toggle. "
                            "Média: turn_on, turn_off, play, pause, stop, volume_up, volume_down, set_volume. "
                            "Serrures: lock, unlock. "
                            "Ventilateurs: turn_on, turn_off, set_speed."
                        ),
                    },
                    "parameters": {
                        "type": "object",
                        "description": (
                            "Paramètres optionnels selon la commande. "
                            "brightness: entier 0-255. temperature: flottant en °C. "
                            "position: entier 0-100. hvac_mode: heat|cool|auto|off. "
                            "volume_level: flottant 0.0-1.0."
                        ),
                        "properties": {
                            "brightness": {"type": "number"},
                            "temperature": {"type": "number"},
                            "position": {"type": "number"},
                            "hvac_mode": {"type": "string"},
                            "volume_level": {"type": "number"},
                            "speed": {"type": "string"},
                        },
                    },
                },
                "required": ["entity_id", "command"],
            },
        )
    ),
]

ALL_TOOLS = [WEB_SEARCH_TOOL] + HA_FUNCTION_TOOLS

# Names of built-in Mistral server-side tools
MISTRAL_BUILTIN_TOOLS = frozenset(
    {
        "web_search",
        "web_search_premium",
        "code_interpreter",
        "image_generation",
        "document_library",
    }
)


# ---------------------------------------------------------------------------
# HA tool executor
# ---------------------------------------------------------------------------


class HAToolExecutor:
    """Executes custom FunctionTools against Home Assistant state."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def execute(self, tool_name: str, arguments: dict) -> str:
        """Dispatch a tool call and return the result as a JSON string."""
        try:
            if tool_name == "get_ha_state":
                result = self._get_ha_state(arguments["entity_id"])
            elif tool_name == "list_ha_entities":
                result = self._list_ha_entities(arguments.get("domain", ""))
            elif tool_name == "get_ha_weather":
                result = self._get_ha_weather()
            elif tool_name == "control_ha_device":
                dc = DeviceController(self.hass)
                result = await dc.control_device(
                    arguments["entity_id"],
                    arguments["command"],
                    arguments.get("parameters") or {},
                )
            else:
                result = {"error": f"Tool inconnu: {tool_name}"}
        except Exception as exc:
            _LOGGER.error(f"Tool execution error [{tool_name}]: {exc}")
            result = {"error": f"échec de l'outil {tool_name}"}

        return json.dumps(result, ensure_ascii=False, default=str)

    def _get_ha_state(self, entity_id: str) -> dict:
        state = self.hass.states.get(entity_id)
        if not state:
            return {"error": f"Entité '{entity_id}' introuvable dans Home Assistant"}
        if state.domain in _BLOCKED_DOMAINS:
            return {"error": f"Le domaine '{state.domain}' n'est pas accessible à l'assistant"}
        return {
            "entity_id": entity_id,
            "state": state.state,
            "friendly_name": state.attributes.get("friendly_name"),
            "attributes": {k: v for k, v in state.attributes.items() if k in _SAFE_ATTRIBUTES},
            "last_changed": state.last_changed.isoformat() if state.last_changed else None,
        }

    def _list_ha_entities(self, domain: str) -> dict:
        if not domain:
            return {
                "error": "Le paramètre 'domain' est requis (light, switch, climate, cover, media_player, sensor, weather, lock, fan)"
            }
        all_states = self.hass.states.async_all(domain)
        states = [s for s in all_states if s.domain not in _BLOCKED_DOMAINS]
        truncated = len(states) > 30
        result = {
            "entities": [
                {
                    "entity_id": s.entity_id,
                    "state": s.state,
                    "name": s.attributes.get("friendly_name", s.entity_id),
                }
                for s in states[:30]
            ],
            "total": len(states),
            "truncated": truncated,
        }
        if truncated:
            result["note"] = (
                f"Only the first 30 of {len(states)} entities are shown. "
                "Call list_ha_entities with a specific domain (light, switch, climate, etc.) "
                "to see all entities for that domain."
            )
        return result

    def _get_ha_weather(self) -> dict:
        weather_states = self.hass.states.async_all("weather")
        if not weather_states:
            return {
                "error": ("Aucune entité météo dans Home Assistant. Installer l'intégration Met.no ou OpenWeatherMap.")
            }
        w = weather_states[0]
        attrs = w.attributes
        return {
            "entity_id": w.entity_id,
            "condition": w.state,
            "temperature": attrs.get("temperature"),
            "temperature_unit": attrs.get("temperature_unit", "°C"),
            "humidity": attrs.get("humidity"),
            "wind_speed": attrs.get("wind_speed"),
            "wind_bearing": attrs.get("wind_bearing"),
            "pressure": attrs.get("pressure"),
            "forecast": (attrs.get("forecast") or [])[:3],
        }
