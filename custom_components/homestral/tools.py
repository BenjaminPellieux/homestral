import json
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant

try:
    from mistralai.client.models import Function, FunctionTool, WebSearchTool
except ImportError:
    from mistralai.models import Function, FunctionTool, WebSearchTool

from .api_control import DeviceController
from .const import CALENDAR_FEATURE_CREATE_EVENT, TOOL_CREATE_CALENDAR_EVENT
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

# Home Assistant's Assist API exposes calendars read-only (calendar_get_events), so
# without this the model can only answer "I cannot add events".
CALENDAR_TOOL = FunctionTool(
    function=Function(
        name=TOOL_CREATE_CALENDAR_EVENT,
        description=(
            "Créer un évènement dans un agenda Home Assistant. "
            "Utilise l'heure locale de la maison. Pour un évènement sur toute la journée, "
            "donne start_date et end_date au lieu des heures."
        ),
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Titre de l'évènement, par exemple 'Signature logement'"},
                "start_date_time": {
                    "type": "string",
                    "description": "Début en heure locale ISO 8601, par exemple 2026-11-05T14:00:00",
                },
                "end_date_time": {
                    "type": "string",
                    "description": "Fin en heure locale ISO 8601. À défaut, duration_minutes est utilisé.",
                },
                "duration_minutes": {
                    "type": "number",
                    "description": "Durée en minutes si la fin n'est pas donnée (60 par défaut).",
                },
                "start_date": {"type": "string", "description": "Jour de début (AAAA-MM-JJ) pour un évènement entier"},
                "end_date": {"type": "string", "description": "Jour de fin exclusif (AAAA-MM-JJ)"},
                "description": {"type": "string", "description": "Détails optionnels"},
                "location": {"type": "string", "description": "Lieu optionnel"},
                "entity_id": {
                    "type": "string",
                    "description": "Agenda cible, par exemple calendar.personnel. Omets-le s'il n'y en a qu'un.",
                },
            },
            "required": ["summary"],
        },
    )
)

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
            elif tool_name == TOOL_CREATE_CALENDAR_EVENT:
                result = await self._create_calendar_event(arguments)
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

    # ------------------------------------------------------------------
    # Calendar
    # ------------------------------------------------------------------

    def writable_calendars(self) -> list[str]:
        """Calendars that accept new events (local_calendar, CalDAV…), read-only ones excluded."""
        return [
            state.entity_id
            for state in self.hass.states.async_all("calendar")
            if int(state.attributes.get("supported_features") or 0) & CALENDAR_FEATURE_CREATE_EVENT
        ]

    def _resolve_calendar(self, requested: str | None) -> str:
        """Pick the target calendar, or explain to the model why it cannot."""
        writable = self.writable_calendars()
        if requested:
            if requested not in writable:
                known = self.hass.states.get(requested)
                if known is None:
                    raise ValueError(f"L'agenda {requested} n'existe pas. Agendas disponibles : {writable or 'aucun'}")
                raise ValueError(f"L'agenda {requested} est en lecture seule, impossible d'y ajouter un évènement.")
            return requested
        if not writable:
            raise ValueError(
                "Aucun agenda modifiable n'est configuré dans Home Assistant. "
                "Ajoute l'intégration « Agenda local » pour pouvoir créer des évènements."
            )
        if len(writable) > 1:
            raise ValueError(f"Plusieurs agendas sont disponibles, précise lequel : {writable}")
        return writable[0]

    @staticmethod
    def _event_window(arguments: dict) -> dict:
        """Turn the model's dates into the fields calendar.create_event expects."""
        if start_date := arguments.get("start_date"):
            start = datetime.fromisoformat(str(start_date)).date()
            end_raw = arguments.get("end_date")
            # An all-day event ends on the following day: the service end date is exclusive.
            end = datetime.fromisoformat(str(end_raw)).date() if end_raw else start + timedelta(days=1)
            if end <= start:
                end = start + timedelta(days=1)
            return {"start_date": start.isoformat(), "end_date": end.isoformat()}

        start_raw = arguments.get("start_date_time")
        if not start_raw:
            raise ValueError("Il manque la date de début (start_date_time ou start_date).")
        start_dt = datetime.fromisoformat(str(start_raw))
        if end_raw := arguments.get("end_date_time"):
            end_dt = datetime.fromisoformat(str(end_raw))
        else:
            minutes = float(arguments.get("duration_minutes") or 60)
            end_dt = start_dt + timedelta(minutes=minutes)
        if end_dt <= start_dt:
            raise ValueError("La fin de l'évènement doit être après son début.")
        return {"start_date_time": start_dt.isoformat(), "end_date_time": end_dt.isoformat()}

    async def _create_calendar_event(self, arguments: dict) -> dict:
        """Create an event through the calendar.create_event service."""
        summary = (arguments.get("summary") or "").strip()
        if not summary:
            return {"error": "Il manque le titre de l'évènement."}
        try:
            entity_id = self._resolve_calendar(arguments.get("entity_id"))
            data = {"summary": summary, **self._event_window(arguments)}
        except ValueError as exc:
            return {"error": str(exc)}

        for key in ("description", "location"):
            if value := arguments.get(key):
                data[key] = str(value)

        _LOGGER.info(f"[CALENDAR] creating {summary!r} on {entity_id}: {data}")
        await self.hass.services.async_call("calendar", "create_event", {"entity_id": entity_id, **data}, blocking=True)
        return {"success": True, "entity_id": entity_id, **data}

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
