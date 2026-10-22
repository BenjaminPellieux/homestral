"""Prompt context and STT vocabulary built from the live Home Assistant state."""

from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import floor_registry as fr

from .const import (
    CONF_STT_BIAS_ENTITIES,
    CONF_STT_CUSTOM_VOCABULARY,
    DEFAULT_STT_BIAS_ENTITIES,
    DEFAULT_STT_CUSTOM_VOCABULARY,
    HOME_AUTOMATION_VOCAB,
    STT_VOCABULARY_CACHE_SECONDS,
    STT_VOCABULARY_MAX_ENTRIES,
)
from .helpers import get_option
from .logging_config import get_logger

_LOGGER = get_logger(__name__)

_VOCABULARY_CACHE_KEY = "stt_vocabulary"
# Entities exposed to this assistant are the ones the user wants to control by voice.
_ASSISTANT = "conversation"


# ---------------------------------------------------------------------------
# STT vocabulary (context_bias)
# ---------------------------------------------------------------------------


def parse_custom_vocabulary(text: str | None) -> list[str]:
    """Split the option text into phrases: one per line, commas also separate entries."""
    if not text:
        return []
    entries = []
    for raw in text.replace(",", "\n").splitlines():
        phrase = " ".join(raw.split())
        if phrase:
            entries.append(phrase)
    return entries


def merge_vocabulary(*groups: Iterable[str], limit: int = STT_VOCABULARY_MAX_ENTRIES) -> list[str]:
    """Flatten the groups in priority order, drop blanks, commas and case-insensitive duplicates, cap the size."""
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for entry in group:
            phrase = " ".join(str(entry).replace(",", " ").split())
            key = phrase.casefold()
            if not phrase or key in seen:
                continue
            seen.add(key)
            merged.append(phrase)
            if len(merged) >= limit:
                return merged
    return merged


def exposed_entity_names(hass: HomeAssistant) -> list[str]:
    """Friendly names of the entities exposed to Assist (the ones worth recognising)."""
    try:
        from homeassistant.components.homeassistant.exposed_entities import async_should_expose
    except ImportError:  # pragma: no cover - always present in Home Assistant
        return []
    names: list[str] = []
    for state in hass.states.async_all():
        try:
            exposed = async_should_expose(hass, _ASSISTANT, state.entity_id)
        except Exception as exc:  # exposure settings not loaded yet
            _LOGGER.debug(f"[STT vocab] exposure lookup failed: {exc}")
            return names
        if not exposed:
            continue
        name = state.attributes.get("friendly_name") or state.name
        if name:
            names.append(str(name))
    return names


def area_and_floor_names(hass: HomeAssistant) -> list[str]:
    names: list[str] = []
    try:
        names.extend(area.name for area in ar.async_get(hass).async_list_areas() if area.name)
        names.extend(floor.name for floor in fr.async_get(hass).async_list_floors() if floor.name)
    except Exception as exc:  # registries not loaded (tests, early startup)
        _LOGGER.debug(f"[STT vocab] registry lookup failed: {exc}")
    return names


async def async_stt_vocabulary(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """The context_bias list for one utterance, cached for a minute on the entry runtime.

    Priority order (the list is capped): the user's custom phrases, the built-in
    home-automation vocabulary, area and floor names, then exposed entity names.
    """
    cache = getattr(getattr(entry, "runtime_data", None), "cache", None)
    now = time.monotonic()
    if isinstance(cache, dict):
        cached = cache.get(_VOCABULARY_CACHE_KEY)
        if cached and now - cached[0] < STT_VOCABULARY_CACHE_SECONDS:
            return list(cached[1])

    groups: list[Iterable[str]] = [
        parse_custom_vocabulary(get_option(entry, CONF_STT_CUSTOM_VOCABULARY, DEFAULT_STT_CUSTOM_VOCABULARY)),
        HOME_AUTOMATION_VOCAB,
    ]
    if get_option(entry, CONF_STT_BIAS_ENTITIES, DEFAULT_STT_BIAS_ENTITIES):
        groups.append(area_and_floor_names(hass))
        groups.append(exposed_entity_names(hass))
    vocabulary = merge_vocabulary(*groups)

    if isinstance(cache, dict):
        cache[_VOCABULARY_CACHE_KEY] = (now, list(vocabulary))
    return vocabulary


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


async def build_ha_context(hass: HomeAssistant, *, legacy_tools: bool = False) -> str:
    """Build the system instructions injected into every Mistral conversation.

    The answer is spoken by a text-to-speech engine, so the prompt asks for short
    spoken sentences without markdown. A trailing question mark makes Home
    Assistant keep the microphone open (``ChatLog.continue_conversation``), which
    is why the model is told to end with a question only for a real clarification.

    With the Home Assistant LLM API active, live state comes from its own tools
    (``GetLiveContext``); the entity-domain listing is only added for entries that
    still rely on HomeStral's legacy tools.
    """
    now = datetime.now()
    lines = [
        "Tu es l'assistant domotique de cette maison, connecté à Home Assistant. Réponds toujours en français.",
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

    if legacy_tools:
        domains = sorted({s.domain for s in hass.states.async_all()})
        if domains:
            lines.append(f"Domaines HA disponibles : {', '.join(domains)}")

    lines.append(
        "Ta réponse est lue à voix haute : fais des phrases courtes et parlées, sans markdown, "
        "sans liste à puces et sans emoji. Une ou deux phrases suffisent."
    )
    lines.append(
        "Utilise les outils pour agir et pour connaître l'état réel de la maison, puis confirme brièvement "
        "ce que tu as fait. Ne dis jamais que tu n'as pas accès à une information si un outil peut y répondre. "
        "Pour les informations extérieures à la maison (météo d'une autre ville, actualités), utilise la recherche web."
    )
    lines.append(
        "Ne termine ta réponse par une question que si tu as vraiment besoin d'une précision pour agir : "
        "le micro reste alors ouvert pour entendre la réponse de l'utilisateur."
    )
    return "\n".join(lines)
