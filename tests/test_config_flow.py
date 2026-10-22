"""Tests for the config and options flow schemas."""

import pytest
import voluptuous as vol

from custom_components.homestral.config_flow import USER_SCHEMA, _options_schema
from custom_components.homestral.const import (
    AVAILABLE_CHAT_MODELS,
    CONF_MODEL,
    DEFAULT_CHAT_MODEL,
)


def test_user_schema_defaults_to_small_4():
    assert USER_SCHEMA({"api_key": "k"})[CONF_MODEL] == DEFAULT_CHAT_MODEL


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
