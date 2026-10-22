"""Tests for the config and options flow schemas."""

import pytest
import voluptuous as vol

from custom_components.homestral.config_flow import USER_SCHEMA, _options_schema
from custom_components.homestral.const import (
    AVAILABLE_CHAT_MODELS,
    CONF_MODEL,
    CONF_STT_BATCH_MODEL,
    CONF_STT_BIAS_ENTITIES,
    CONF_STT_CHAT_FALLBACK,
    CONF_STT_CUSTOM_VOCABULARY,
    CONF_STT_LANGUAGE,
    CONF_STT_MODE,
    CONF_STT_STREAMING_DELAY_MS,
    CONF_STT_TURN_DETECTION,
    CONF_TTS_DEFAULT_EMOTION,
    CONF_TTS_DEFAULT_PACE,
    CONF_TTS_EXPRESSIVENESS,
    CONF_TTS_VOICE,
    DEFAULT_CHAT_MODEL,
    DEFAULT_STT_BATCH_MODEL,
    DEFAULT_STT_LANGUAGE,
    DEFAULT_STT_MODE,
    DEFAULT_STT_STREAMING_DELAY_MS,
    DEFAULT_STT_TURN_DETECTION,
    TTS_NONE,
)


def test_user_schema_defaults_to_small_4_and_has_no_stt_fields():
    validated = USER_SCHEMA({"api_key": "k"})
    assert validated[CONF_MODEL] == DEFAULT_CHAT_MODEL
    assert CONF_STT_MODE not in validated


def test_options_schema_maps_legacy_model_id_to_current_alias():
    """An entry created with the old pinned id still opens the options form."""
    schema = _options_schema({CONF_MODEL: "mistral-large-4"})

    assert schema({})[CONF_MODEL] == "mistral-large-latest"


def test_options_schema_unknown_model_falls_back_to_default():
    schema = _options_schema({CONF_MODEL: "no-such-model"})

    assert schema({})[CONF_MODEL] == DEFAULT_CHAT_MODEL


def test_options_schema_rejects_model_outside_list():
    schema = _options_schema({})

    with pytest.raises(vol.Invalid):
        schema({CONF_MODEL: "mistral-large-4"})
    for model in AVAILABLE_CHAT_MODELS:
        assert schema({CONF_MODEL: model})[CONF_MODEL] == model


def test_options_schema_stt_defaults():
    validated = _options_schema({})({})

    assert validated[CONF_STT_MODE] == DEFAULT_STT_MODE == "realtime"
    assert validated[CONF_STT_TURN_DETECTION] == DEFAULT_STT_TURN_DETECTION == "default"
    assert validated[CONF_STT_STREAMING_DELAY_MS] == DEFAULT_STT_STREAMING_DELAY_MS == 480
    assert validated[CONF_STT_LANGUAGE] == DEFAULT_STT_LANGUAGE == "pipeline"
    assert validated[CONF_STT_BATCH_MODEL] == DEFAULT_STT_BATCH_MODEL == "mini"
    assert validated[CONF_STT_CUSTOM_VOCABULARY] == ""
    assert validated[CONF_STT_BIAS_ENTITIES] is True
    assert validated[CONF_STT_CHAT_FALLBACK] is False


def test_options_schema_stt_validation_and_round_trip():
    schema = _options_schema({})

    assert schema({CONF_STT_STREAMING_DELAY_MS: "960"})[CONF_STT_STREAMING_DELAY_MS] == 960
    with pytest.raises(vol.Invalid):
        schema({CONF_STT_STREAMING_DELAY_MS: 500})
    with pytest.raises(vol.Invalid):
        schema({CONF_STT_TURN_DETECTION: "wild"})
    with pytest.raises(vol.Invalid):
        schema({CONF_STT_MODE: "stream"})

    stored = {
        CONF_STT_MODE: "batch",
        CONF_STT_TURN_DETECTION: "aggressive",
        CONF_STT_STREAMING_DELAY_MS: 240,
        CONF_STT_LANGUAGE: "auto",
        CONF_STT_BATCH_MODEL: "small",
        CONF_STT_CUSTOM_VOCABULARY: "ma prise\nGrand-mère",
        CONF_STT_BIAS_ENTITIES: False,
        CONF_STT_CHAT_FALLBACK: True,
    }
    assert {key: _options_schema(stored)({})[key] for key in stored} == stored


def test_options_schema_tts_defaults():
    validated = _options_schema({})({})

    assert validated[CONF_TTS_VOICE] == ""
    assert validated[CONF_TTS_DEFAULT_EMOTION] == TTS_NONE
    assert validated[CONF_TTS_DEFAULT_PACE] == TTS_NONE
    assert validated[CONF_TTS_EXPRESSIVENESS] == 0.0


def test_options_schema_tts_validation_and_round_trip():
    schema = _options_schema({})

    # 0 keeps the service default, 1.0 to 5.0 is the documented range.
    assert schema({CONF_TTS_EXPRESSIVENESS: 0})[CONF_TTS_EXPRESSIVENESS] == 0.0
    assert schema({CONF_TTS_EXPRESSIVENESS: "3.5"})[CONF_TTS_EXPRESSIVENESS] == 3.5
    for invalid in (0.5, 5.5, -1):
        with pytest.raises(vol.Invalid):
            schema({CONF_TTS_EXPRESSIVENESS: invalid})
    with pytest.raises(vol.Invalid):
        schema({CONF_TTS_DEFAULT_EMOTION: "ecstatic"})
    with pytest.raises(vol.Invalid):
        schema({CONF_TTS_DEFAULT_PACE: "turbo"})

    stored = {
        CONF_TTS_VOICE: "voice_3137",
        CONF_TTS_DEFAULT_EMOTION: "calm",
        CONF_TTS_DEFAULT_PACE: "slow",
        CONF_TTS_EXPRESSIVENESS: 2.5,
    }
    assert {key: _options_schema(stored)({})[key] for key in stored} == stored
