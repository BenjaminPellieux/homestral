import json
from datetime import datetime
from homeassistant.core import HomeAssistant

try:
    from mistralai.client.models import FunctionTool, Function, WebSearchTool
except ImportError:
    from mistralai.models import FunctionTool, Function, WebSearchTool

from .api_control import DeviceController
from .logging_config import get_logger

_LOGGER = get_logger(__name__)

# ---------------------------------------------------------------------------
# Built-in Mistral tools (server-side, no client execution needed)
# ---------------------------------------------------------------------------

WEB_SEARCH_TOOL = WebSearchTool()

# ---------------------------------------------------------------------------
# Custom HA FunctionTools (client-side execution via HAToolExecutor)
# ---------------------------------------------------------------------------

HA_FUNCTION_TOOLS = [
    FunctionTool(function=Function(
        name="get_ha_state",
        description=(
            "Obtenir l'état actuel d'une entité Home Assistant "
            "(lumière, thermostat, capteur, couverture, etc.)"
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
    )),
    FunctionTool(function=Function(
        name="list_ha_entities",
        description="Lister les entités d'un domaine Home Assistant avec leur état actuel",
        parameters={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Domaine HA: light, switch, climate, cover, media_player, sensor, weather, lock, fan",
                    "enum": [
                        "light", "switch", "climate", "cover",
                        "media_player", "sensor", "weather", "lock", "fan",
                    ],
                }
            },
            "required": ["domain"],
        },
    )),
    FunctionTool(function=Function(
        name="get_ha_weather",
        description="Obtenir la météo locale depuis les entités météo de Home Assistant",
        parameters={"type": "object", "properties": {}, "required": []},
    )),
    FunctionTool(function=Function(
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
    )),
]

ALL_TOOLS = [WEB_SEARCH_TOOL] + HA_FUNCTION_TOOLS

# Names of built-in Mistral server-side tools
MISTRAL_BUILTIN_TOOLS = frozenset({
    "web_search", "web_search_premium",
    "code_interpreter", "image_generation", "document_library",
})


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
            result = {"error": str(exc)}

        return json.dumps(result, ensure_ascii=False, default=str)

    def _get_ha_state(self, entity_id: str) -> dict:
        state = self.hass.states.get(entity_id)
        if not state:
            return {"error": f"Entité '{entity_id}' introuvable dans Home Assistant"}
        return {
            "entity_id": entity_id,
            "state": state.state,
            "friendly_name": state.attributes.get("friendly_name"),
            "attributes": dict(state.attributes),
            "last_changed": state.last_changed.isoformat() if state.last_changed else None,
        }

    def _list_ha_entities(self, domain: str) -> dict:
        states = (
            self.hass.states.async_all(domain) if domain
            else self.hass.states.async_all()
        )
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
                "error": (
                    "Aucune entité météo dans Home Assistant. "
                    "Installer l'intégration Met.no ou OpenWeatherMap."
                )
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


# ---------------------------------------------------------------------------
# System context builder
# ---------------------------------------------------------------------------

async def build_ha_context(hass: HomeAssistant) -> str:
    """Build the system instructions injected into every Mistral conversation."""
    now = datetime.now()
    lines = [
        "Tu es un assistant domotique intelligent pour Home Assistant. Réponds toujours en français.",
        f"Date et heure actuelles : {now.strftime('%A %d %B %Y à %H:%M')}",
    ]

    weather_states = hass.states.async_all("weather")
    if weather_states:
        w = weather_states[0]
        a = w.attributes
        lines.append(
            f"Météo locale ({w.entity_id}) : {a.get('temperature')}"
            f"{a.get('temperature_unit', '°C')}, {w.state}"
            + (f", humidité {a.get('humidity')}%" if a.get("humidity") else "")
        )

    domains = sorted({s.domain for s in hass.states.async_all()})
    if domains:
        lines.append(f"Domaines HA disponibles : {', '.join(domains)}")

    lines.append(
        "Instructions : utilise les tools HA pour accéder aux données et contrôler les appareils. "
        "Utilise control_ha_device pour allumer/éteindre des lumières, régler le chauffage, ouvrir les volets, etc. "
        "Utilise get_ha_state ou list_ha_entities pour connaître l'état actuel avant d'agir si nécessaire. "
        "Pour les informations externes (météo d'autres villes, actualités, etc.), utilise la recherche web. "
        "Ne dis jamais que tu n'as pas accès aux données si un tool peut y répondre."
    )
    return "\n".join(lines)
