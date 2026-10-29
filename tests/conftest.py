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

# Before voluptuous, as in Home Assistant itself: from 2026.9 importing homeassistant
# installs probatio's voluptuous shim, and a voluptuous imported earlier is not the shim.
import homeassistant  # noqa: F401
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
            self._materialize(delta)
            yield delta

    def _materialize(self, delta: dict[str, Any]) -> None:
        """Turn a delta into chat-log content, as Home Assistant's chat log does.

        The Responses backend rebuilds its request from this content, so the fake
        has to grow the log across the iterations of a tool loop.
        """
        if delta.get("role") == "assistant":
            self.content.append(SimpleNamespace(role="assistant", content="", tool_calls=[]))
        elif delta.get("role") == "tool_result":
            self.content.append(
                SimpleNamespace(
                    role="tool_result",
                    tool_call_id=delta.get("tool_call_id", ""),
                    tool_name=delta.get("tool_name", ""),
                    tool_result=delta.get("tool_result"),
                )
            )
        elif self.content and getattr(self.content[-1], "role", None) == "assistant":
            if "content" in delta:
                self.content[-1].content += delta["content"]
            if "tool_calls" in delta:
                self.content[-1].tool_calls = list(delta["tool_calls"])

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


# ---------------------------------------------------------------------------
# Mistral Responses stream events and output items (experimental backend)
# ---------------------------------------------------------------------------


def resp_text_delta(text: str):
    return SimpleNamespace(data=SimpleNamespace(type="response.output_text.delta", delta=text))


def resp_function_call(name: str, arguments: str, call_id: str = "call_1"):
    """One ``function_call`` item of a response ``output`` array."""
    return SimpleNamespace(type="function_call", name=name, arguments=arguments, call_id=call_id)


def resp_message(text: str):
    """One ``message`` item of a response ``output`` array."""
    return SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])


def resp_completed(*output: Any):
    return SimpleNamespace(
        data=SimpleNamespace(type="response.completed", response=SimpleNamespace(output=list(output)))
    )


def resp_incomplete(*output: Any):
    return SimpleNamespace(
        data=SimpleNamespace(type="response.incomplete", response=SimpleNamespace(output=list(output)))
    )


def resp_failed(message: str = "quota exceeded"):
    return SimpleNamespace(data=SimpleNamespace(type="response.failed", message=message))


def make_responses_client(*scripts: Any):
    """A Mistral client whose ``responses.create_async`` replays the given scripts.

    A script that is a list drives a streaming call (the events of one response);
    anything else is returned as the response object of a non-streaming call.
    """
    client = MagicMock()
    calls: list[dict[str, Any]] = []
    remaining = list(scripts)

    async def _create(**kwargs):
        calls.append(kwargs)
        script = remaining.pop(0) if remaining else [resp_text_delta("ok"), resp_completed()]
        if kwargs.get("stream"):
            return FakeEventStream(script if isinstance(script, list) else [script])
        return script

    client.responses.create_async = AsyncMock(side_effect=_create)
    client.responses_calls = calls
    return client


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
