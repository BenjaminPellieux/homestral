"""Tests for the Homestral sensor.

Regression: the Mistral API key must never appear in the logs.
"""

import logging
from unittest.mock import MagicMock

import pytest

from homestral.sensor import HomestralSensor, async_setup_entry

SECRET = "sk-test-secret-key-123"


def test_sensor_init_does_not_log_api_key(caplog):
    with caplog.at_level(logging.INFO):
        HomestralSensor(SECRET)
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_sensor_setup_entry_does_not_log_api_key(caplog):
    entry = MagicMock()
    entry.data = {"api_key": SECRET}
    async_add_entities = MagicMock()

    with caplog.at_level(logging.INFO):
        await async_setup_entry(MagicMock(), entry, async_add_entities)

    assert SECRET not in caplog.text
    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]
    assert len(entities) == 1
    assert isinstance(entities[0], HomestralSensor)


def test_sensor_entity_attributes():
    sensor = HomestralSensor(SECRET)
    assert sensor.name == "Homestral Sensor"
    assert sensor.unique_id == "homestral_sensor"
    assert sensor.device_info["identifiers"] == {("homestral", "homestral")}
