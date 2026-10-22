"""Tests for the STT vocabulary builder and the system prompt (context_builder.py)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.homestral import context_builder as cb
from custom_components.homestral.const import (
    CONF_STT_BIAS_ENTITIES,
    CONF_STT_CUSTOM_VOCABULARY,
    HOME_AUTOMATION_VOCAB,
    STT_VOCABULARY_MAX_ENTRIES,
)


def _state(entity_id, friendly_name=None, name=None):
    state = MagicMock()
    state.entity_id = entity_id
    state.domain = entity_id.split(".")[0]
    state.attributes = {"friendly_name": friendly_name} if friendly_name else {}
    state.name = name or entity_id
    return state


def test_parse_custom_vocabulary_accepts_lines_and_commas():
    text = "volet du salon\n lampe   cuisine , prise TV\n\n,\n"
    assert cb.parse_custom_vocabulary(text) == ["volet du salon", "lampe cuisine", "prise TV"]
    assert cb.parse_custom_vocabulary("") == []
    assert cb.parse_custom_vocabulary(None) == []


def test_merge_vocabulary_dedupes_strips_commas_and_caps():
    merged = cb.merge_vocabulary(["A", "a", " b , c ", ""], ["B C", "d", "e"], limit=3)
    assert merged == ["A", "b c", "d"]
    assert len(cb.merge_vocabulary(str(i) for i in range(500))) == STT_VOCABULARY_MAX_ENTRIES


def test_exposed_entity_names_filters_on_assist_exposure():
    hass = MagicMock()
    hass.states.async_all.return_value = [
        _state("light.salon", "Lampe salon"),
        _state("sensor.hidden", "Capteur caché"),
        _state("switch.prise", name="Prise TV"),
    ]
    exposed = {"light.salon", "switch.prise"}
    with patch(
        "homeassistant.components.homeassistant.exposed_entities.async_should_expose",
        side_effect=lambda hass, assistant, entity_id: entity_id in exposed,
    ) as should_expose:
        names = cb.exposed_entity_names(hass)

    assert names == ["Lampe salon", "Prise TV"]
    assert should_expose.call_args.args[1] == "conversation"


def test_exposed_entity_names_without_exposure_data_returns_nothing():
    hass = MagicMock()
    hass.states.async_all.return_value = [_state("light.salon", "Lampe salon")]
    with patch(
        "homeassistant.components.homeassistant.exposed_entities.async_should_expose",
        side_effect=KeyError("exposed_entities"),
    ):
        assert cb.exposed_entity_names(hass) == []


def test_area_and_floor_names():
    areas = MagicMock()
    areas.async_list_areas.return_value = [SimpleNamespace(name="Salon"), SimpleNamespace(name="")]
    floors = MagicMock()
    floors.async_list_floors.return_value = [SimpleNamespace(name="Étage")]
    with patch.object(cb.ar, "async_get", return_value=areas), patch.object(cb.fr, "async_get", return_value=floors):
        assert cb.area_and_floor_names(MagicMock()) == ["Salon", "Étage"]
    with patch.object(cb.ar, "async_get", side_effect=KeyError("area_registry")):
        assert cb.area_and_floor_names(MagicMock()) == []


def _entry(options, cache=True):
    entry = MagicMock()
    entry.data = {"api_key": "k"}
    entry.options = options
    entry.runtime_data = SimpleNamespace(cache={}) if cache else None
    return entry


@pytest.mark.asyncio
async def test_async_stt_vocabulary_priority_and_cache():
    entry = _entry({CONF_STT_CUSTOM_VOCABULARY: "ma prise, Grand-mère", CONF_STT_BIAS_ENTITIES: True})
    with (
        patch.object(cb, "area_and_floor_names", return_value=["Salon"]),
        patch.object(cb, "exposed_entity_names", return_value=["Lampe salon", "lumière"]),
    ):
        vocabulary = await cb.async_stt_vocabulary(MagicMock(), entry)

    assert vocabulary[:2] == ["ma prise", "Grand-mère"]
    assert all(entry_ in vocabulary for entry_ in HOME_AUTOMATION_VOCAB)
    assert vocabulary.index("Salon") < vocabulary.index("Lampe salon")
    assert vocabulary.count("lumière") == 1  # case-insensitive duplicate of the built-in entry
    assert "stt_vocabulary" in entry.runtime_data.cache

    # Cached for a minute: changed registries are not consulted again
    with patch.object(cb, "exposed_entity_names", return_value=["Nouvelle lampe"]) as names:
        again = await cb.async_stt_vocabulary(MagicMock(), entry)
    assert again == vocabulary
    names.assert_not_called()


@pytest.mark.asyncio
async def test_async_stt_vocabulary_without_entity_bias_and_without_cache():
    entry = _entry({CONF_STT_BIAS_ENTITIES: False}, cache=False)
    with (
        patch.object(cb, "area_and_floor_names", return_value=["Salon"]) as areas,
        patch.object(cb, "exposed_entity_names", return_value=["Lampe salon"]) as names,
    ):
        vocabulary = await cb.async_stt_vocabulary(MagicMock(), entry)

    assert vocabulary == list(HOME_AUTOMATION_VOCAB)
    areas.assert_not_called()
    names.assert_not_called()


@pytest.mark.asyncio
async def test_build_ha_context_mentions_weather_and_domains():
    hass = MagicMock()
    weather = _state("weather.maison")
    weather.state = "sunny"
    weather.attributes = {"temperature": 21, "humidity": 40}
    hass.states.async_all.side_effect = lambda domain=None: (
        [weather] if domain == "weather" else [weather, _state("light.a")]
    )

    context = await cb.build_ha_context(hass)

    assert "Date et heure actuelles" in context
    assert "weather.maison" in context and "21°C" in context and "humidité 40%" in context
    # Spoken-answer guidance replaces the markdown-friendly phrasing
    assert "lue à voix haute" in context
    assert "que si tu as vraiment besoin d'une précision" in context
    # With the Home Assistant LLM API, live state comes from GetLiveContext, not a domain dump
    assert "Domaines HA disponibles" not in context

    legacy_context = await cb.build_ha_context(hass, legacy_tools=True)
    assert "Domaines HA disponibles : light, weather" in legacy_context
