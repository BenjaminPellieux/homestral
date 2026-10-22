"""Bridge between the Home Assistant LLM API and Mistral function tools.

Home Assistant exposes its own tools (``HassTurnOn``, ``HassSetPosition``,
``GetLiveContext``, calendar and todo helpers, ...) through ``helpers/llm.py``.
They carry voluptuous schemas and are executed by Home Assistant itself, which
applies the "exposed to Assist" setting and resolves the area of the satellite
that is speaking. This module converts them to the ``FunctionTool`` shape the
Mistral Conversations API expects and routes execution back.
"""

from __future__ import annotations

import json
from typing import Any

from homeassistant.helpers import llm
from mistralai.client.models import Function, FunctionTool
from voluptuous_openapi import convert

from .logging_config import get_logger
from .tools import HA_FUNCTION_TOOLS, WEB_SEARCH_TOOL, HAToolExecutor

_LOGGER = get_logger(__name__)

# Names of HomeStral's own tools, used to route a call to HAToolExecutor.
LEGACY_TOOL_NAMES = frozenset(
    tool.function.name for tool in HA_FUNCTION_TOOLS if getattr(getattr(tool, "function", None), "name", None)
)


def ha_tool_to_mistral(tool: llm.Tool, custom_serializer: Any = None) -> FunctionTool:
    """Convert one Home Assistant LLM tool to a Mistral FunctionTool."""
    parameters = convert(tool.parameters, custom_serializer=custom_serializer)
    return FunctionTool(
        function=Function(
            name=tool.name,
            description=tool.description or f"Home Assistant {tool.name} intent",
            parameters=parameters,
        )
    )


def build_tools(llm_api: llm.APIInstance | None, *, legacy_tools: bool, web_search: bool = True) -> list[Any]:
    """Assemble the tool list sent to Mistral.

    Home Assistant tools come first and win a name collision, since they respect
    the exposure settings that HomeStral's own tools bypass.
    """
    tools: list[Any] = []
    names: set[str] = set()

    if llm_api is not None:
        for tool in llm_api.tools:
            try:
                tools.append(ha_tool_to_mistral(tool, llm_api.custom_serializer))
            except Exception as exc:  # a malformed schema must not break the whole turn
                _LOGGER.warning(f"[TOOLS] skipping Home Assistant tool {tool.name!r}: {exc}")
                continue
            names.add(tool.name)

    if web_search:
        tools.append(WEB_SEARCH_TOOL)

    if legacy_tools:
        for tool in HA_FUNCTION_TOOLS:
            name = tool.function.name
            if name in names:
                _LOGGER.debug(f"[TOOLS] legacy tool {name!r} shadowed by the Home Assistant tool of the same name")
                continue
            tools.append(tool)
            names.add(name)

    _LOGGER.debug(f"[TOOLS] {len(tools)} tools sent: {sorted(names)}")
    return tools


def parse_arguments(arguments: Any) -> dict[str, Any]:
    """Decode the ``arguments`` field of a function call (a JSON string or a mapping)."""
    if isinstance(arguments, dict):
        return arguments
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid tool arguments: {arguments!r}") from exc
    return parsed if isinstance(parsed, dict) else {}


class ToolRouter:
    """Execute a tool call either through the Home Assistant LLM API or HomeStral's executor."""

    def __init__(self, llm_api: llm.APIInstance | None, executor: HAToolExecutor, *, legacy_tools: bool) -> None:
        self._llm_api = llm_api
        self._executor = executor
        self._legacy_tools = legacy_tools

    def knows(self, name: str) -> bool:
        if self._llm_api is not None and any(tool.name == name for tool in self._llm_api.tools):
            return True
        return self._legacy_tools and name in LEGACY_TOOL_NAMES

    async def async_call(self, name: str, arguments: Any) -> Any:
        """Run the tool and return a JSON-serialisable result (never raises)."""
        try:
            args = parse_arguments(arguments)
        except ValueError as exc:
            return {"error": str(exc)}

        if self._llm_api is not None and any(tool.name == name for tool in self._llm_api.tools):
            try:
                return await self._llm_api.async_call_tool(llm.ToolInput(tool_name=name, tool_args=args))
            except Exception as exc:
                _LOGGER.error(f"[TOOL ha] {name}: {exc}")
                return {"error": str(exc)}

        if self._legacy_tools and name in LEGACY_TOOL_NAMES:
            try:
                return json.loads(await self._executor.execute(name, args))
            except Exception as exc:
                _LOGGER.error(f"[TOOL legacy] {name}: {exc}")
                return {"error": str(exc)}

        _LOGGER.warning(f"[TOOL] unknown tool requested: {name!r}")
        return {"error": f"Tool inconnu: {name}"}
