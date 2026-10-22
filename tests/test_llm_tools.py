"""Tests for the Home Assistant LLM API bridge (llm_tools.py)."""

import json
from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from conftest import FakeLLMApi, FakeTool

from custom_components.homestral.llm_tools import (
    LEGACY_TOOL_NAMES,
    ToolRouter,
    build_tools,
    ha_tool_to_mistral,
    parse_arguments,
)
from custom_components.homestral.tools import HA_FUNCTION_TOOLS, HAToolExecutor


def _names(tools):
    return [getattr(getattr(tool, "function", None), "name", type(tool).__name__) for tool in tools]


def test_ha_tool_is_converted_to_a_mistral_function_tool():
    tool = FakeTool("HassTurnOn", "Turn on a device", vol.Schema({vol.Required("name"): str}))

    converted = ha_tool_to_mistral(tool)

    assert converted.function.name == "HassTurnOn"
    assert converted.function.description == "Turn on a device"
    assert converted.function.parameters["type"] == "object"
    assert "name" in converted.function.parameters["properties"]
    assert converted.function.parameters["required"] == ["name"]


def test_build_tools_sends_ha_tools_and_web_search_by_default():
    tools = build_tools(FakeLLMApi(), legacy_tools=False)

    names = _names(tools)
    assert "HassTurnOn" in names and "GetLiveContext" in names
    assert "WebSearchTool" in names  # the built-in server-side tool
    # No HomeStral tool when the legacy option is off
    assert "control_ha_device" not in names


def test_build_tools_adds_legacy_tools_when_enabled():
    tools = build_tools(FakeLLMApi(), legacy_tools=True)

    names = _names(tools)
    assert "control_ha_device" in names
    assert set(LEGACY_TOOL_NAMES) <= set(names)


def test_build_tools_lets_home_assistant_win_a_name_collision():
    """A HomeStral tool is dropped when Home Assistant exposes the same name."""
    colliding = FakeLLMApi(tools=[FakeTool("control_ha_device")])

    names = _names(build_tools(colliding, legacy_tools=True))

    assert names.count("control_ha_device") == 1


def test_build_tools_without_llm_api_falls_back_to_legacy_only():
    assert _names(build_tools(None, legacy_tools=False)) == ["WebSearchTool"]
    names = _names(build_tools(None, legacy_tools=True))
    assert len(names) == 1 + len(HA_FUNCTION_TOOLS)


def test_build_tools_skips_a_tool_whose_schema_cannot_be_read():
    """One broken tool must not cost the user the whole turn."""

    class BrokenTool:
        name = "Broken"
        description = "boom"

        @property
        def parameters(self):
            raise RuntimeError("schema unavailable")

    broken = FakeLLMApi(tools=[BrokenTool(), FakeTool("HassTurnOn")])

    names = _names(build_tools(broken, legacy_tools=False))

    assert "HassTurnOn" in names
    assert "Broken" not in names


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ({"a": 1}, {"a": 1}),
        ("", {}),
        (None, {}),
        ("[1, 2]", {}),  # a non-object payload carries no named arguments
    ],
)
def test_parse_arguments(raw, expected):
    assert parse_arguments(raw) == expected


def test_parse_arguments_rejects_broken_json():
    with pytest.raises(ValueError, match="invalid tool arguments"):
        parse_arguments("{not json")


@pytest.mark.asyncio
async def test_router_sends_known_ha_tools_to_home_assistant():
    llm_api = FakeLLMApi(result={"speech": "ok"})
    router = ToolRouter(llm_api, HAToolExecutor(MagicMock()), legacy_tools=False)

    assert router.knows("HassTurnOn") is True
    result = await router.async_call("HassTurnOn", '{"name": "salon"}')

    assert result == {"speech": "ok"}
    assert llm_api.calls[0].tool_args == {"name": "salon"}


@pytest.mark.asyncio
async def test_router_reports_home_assistant_tool_failures_as_results():
    llm_api = FakeLLMApi(error=RuntimeError("entity not exposed"))
    router = ToolRouter(llm_api, HAToolExecutor(MagicMock()), legacy_tools=False)

    assert await router.async_call("HassTurnOn", "{}") == {"error": "entity not exposed"}


@pytest.mark.asyncio
async def test_router_sends_legacy_tools_to_the_homestral_executor():
    executor = HAToolExecutor(MagicMock())
    executor.execute = MagicMock(return_value=json.dumps({"success": True}))

    async def execute(name, args):
        return executor.execute(name, args)

    executor_wrapper = MagicMock()
    executor_wrapper.execute = execute
    router = ToolRouter(FakeLLMApi(), executor_wrapper, legacy_tools=True)

    assert router.knows("control_ha_device") is True
    assert await router.async_call("control_ha_device", '{"entity_id": "light.a"}') == {"success": True}


@pytest.mark.asyncio
async def test_router_refuses_unknown_and_disabled_tools():
    router = ToolRouter(FakeLLMApi(), HAToolExecutor(MagicMock()), legacy_tools=False)

    assert router.knows("control_ha_device") is False
    assert "error" in await router.async_call("control_ha_device", "{}")
    assert "error" in await router.async_call("nope", "{}")


@pytest.mark.asyncio
async def test_router_reports_broken_arguments():
    router = ToolRouter(FakeLLMApi(), HAToolExecutor(MagicMock()), legacy_tools=False)

    assert "error" in await router.async_call("HassTurnOn", "{broken")
