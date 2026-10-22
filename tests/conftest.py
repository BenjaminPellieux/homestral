"""Shared fixtures and fakes for the HomeStral test suite.

The conversation entity streams its answer into a Home Assistant ``ChatLog``:
the runner yields delta dicts, the chat log turns them into content and executes
the tools that are not marked ``external``. The fakes below reproduce just
enough of that contract (plus the LLM API) to drive the runner without Home
Assistant's own test harness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
from homeassistant.helpers import llm


@dataclass
class FakeTool:
    """Stand-in for an llm.Tool exposed by a Home Assistant LLM API."""

    name: str
    description: str = "fake tool"
    parameters: vol.Schema = field(default_factory=lambda: vol.Schema({vol.Optional("name"): str}))


class FakeLLMApi:
    """Stand-in for llm.APIInstance: tools plus the execution entry point."""

    def __init__(self, tools: list[FakeTool] | None = None, result: Any = None, error: Exception | None = None):
        self.tools = tools if tools is not None else [FakeTool("HassTurnOn"), FakeTool("GetLiveContext")]
        self.custom_serializer = None
        self.api_prompt = "Assist API prompt"
        self.calls: list[llm.ToolInput] = []
        self._result = result if result is not None else {"success": True}
        self._error = error

    async def async_call_tool(self, tool_input: llm.ToolInput) -> Any:
        self.calls.append(tool_input)
        if self._error is not None:
            raise self._error
        return self._result


class FakeChatLog:
    """Minimal ChatLog: records the deltas and runs the coroutines they carry."""

    def __init__(self, llm_api: FakeLLMApi | None = None, prompt: str = "system prompt"):
        self.llm_api = llm_api
        self.content: list[Any] = [SimpleNamespace(role="system", content=prompt)]
        self.deltas: list[dict[str, Any]] = []
        self.llm_data_calls: list[tuple] = []
        self.unresponded_tool_results = False

    async def async_provide_llm_data(self, llm_context, apis=None, prompt=None, extra_system_prompt=None) -> None:
        self.llm_data_calls.append((llm_context, apis, prompt, extra_system_prompt))

    async def async_add_delta_content_stream(self, agent_id: str, stream):
        """Consume the runner's deltas, as Home Assistant's chat log does."""
        self.agent_id = agent_id
        async for delta in stream:
            self.deltas.append(delta)
            yield delta

    # -- helpers used by the assertions -------------------------------

    @property
    def text(self) -> str:
        return "".join(delta.get("content", "") for delta in self.deltas if "content" in delta)

    @property
    def tool_calls(self) -> list[llm.ToolInput]:
        calls: list[llm.ToolInput] = []
        for delta in self.deltas:
            calls.extend(delta.get("tool_calls") or [])
        return calls

    @property
    def tool_results(self) -> list[dict[str, Any]]:
        return [delta for delta in self.deltas if delta.get("role") == "tool_result"]

    @property
    def roles(self) -> list[str]:
        return [delta["role"] for delta in self.deltas if "role" in delta]


def make_user_input(text: str = "Allume la lumière", conversation_id: str | None = "ha_conv", **kwargs):
    """A ConversationInput stand-in exposing as_llm_context()."""
    user_input = MagicMock()
    user_input.text = text
    user_input.conversation_id = conversation_id
    user_input.agent_id = kwargs.get("agent_id", "conversation.homestral")
    user_input.extra_system_prompt = kwargs.get("extra_system_prompt")
    user_input.as_llm_context = MagicMock(
        return_value=llm.LLMContext(
            platform="homestral",
            context=None,
            language=kwargs.get("language", "fr"),
            assistant="conversation",
            device_id=kwargs.get("device_id"),
        )
    )
    return user_input


# ---------------------------------------------------------------------------
# Mistral conversation stream events
# ---------------------------------------------------------------------------


def started_event(conversation_id: str = "conv_1"):
    return SimpleNamespace(data=SimpleNamespace(type="conversation.response.started", conversation_id=conversation_id))


def text_event(content: str):
    return SimpleNamespace(data=SimpleNamespace(type="message.output.delta", content=content))


def call_event(name: str, arguments: str, tool_call_id: str = "call_1", output_index: int = 0):
    return SimpleNamespace(
        data=SimpleNamespace(
            type="function.call.delta",
            id=tool_call_id,
            tool_call_id=tool_call_id,
            name=name,
            arguments=arguments,
            output_index=output_index,
        )
    )


def tool_execution_event(name: str = "web_search", done: bool = True, arguments: str = "{}"):
    return SimpleNamespace(
        data=SimpleNamespace(
            type=f"tool.execution.{'done' if done else 'started'}",
            id=f"srv_{name}",
            name=name,
            arguments=arguments,
        )
    )


def done_event():
    return SimpleNamespace(data=SimpleNamespace(type="conversation.response.done"))


def error_event(message: str = "quota exceeded"):
    return SimpleNamespace(data=SimpleNamespace(type="conversation.response.error", message=message))


class FakeEventStream:
    """Async context manager yielding scripted conversation events."""

    def __init__(self, events: list[Any]):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for event in self._events:
            yield event


def make_streaming_client(*scripts: list[Any]):
    """A Mistral client whose start/append stream calls return the given scripts in order."""
    client = MagicMock()
    calls: list[dict[str, Any]] = []
    remaining = list(scripts)

    async def _open(**kwargs):
        calls.append(kwargs)
        events = remaining.pop(0) if remaining else [started_event(), text_event("ok"), done_event()]
        return FakeEventStream(events)

    client.beta.conversations.start_stream_async = AsyncMock(side_effect=_open)
    client.beta.conversations.append_stream_async = AsyncMock(side_effect=_open)
    client.stream_calls = calls
    return client


def tool_result_payload(delta: dict[str, Any]) -> Any:
    """Decode a tool_result delta the way the next request would."""
    result = delta["tool_result"]
    return json.loads(result) if isinstance(result, str) else result


@pytest.fixture
def chat_log() -> FakeChatLog:
    return FakeChatLog(FakeLLMApi())
