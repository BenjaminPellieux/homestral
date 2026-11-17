"""Experimental turn runner for the Mistral Responses API (public preview).

Unlike the Conversations API the default runner uses, the Responses API is
stateless: Mistral stores nothing, so the whole history travels with every
request. ``ResponsesTurnRunner`` rebuilds it from the Home Assistant chat log,
which makes the context survive a restart and keeps the thread where Home
Assistant already keeps it — the same approach the core LLM integrations take.

The trade-off is that only client-executed function tools exist on this API:
Mistral's built-in web search and the Mistral agents are unavailable here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

from .agent import (
    NO_ANSWER_MESSAGE,
    NO_RESPONSE_MESSAGE,
    TOO_MANY_STEPS_MESSAGE,
    PendingCall,
    event_data,
    event_type,
    instructions_from_chat_log,
    iter_stream,
    provide_llm_data,
    run_tool_call,
    safe_args,
)
from .const import (
    CONF_CONFIRM_SENSITIVE,
    CONF_LEGACY_TOOLS,
    CONF_MAX_TOOL_ITERATIONS,
    CONF_MODEL,
    DEFAULT_CONFIRM_SENSITIVE,
    DEFAULT_LEGACY_TOOLS,
    DEFAULT_MAX_TOOL_ITERATIONS,
    resolve_chat_model,
)
from .context_builder import build_ha_context
from .helpers import get_option
from .llm_tools import ToolRouter, build_tools, to_responses_tools
from .logging_config import get_logger
from .tools import ALL_TOOLS, HA_FUNCTION_TOOLS, HAToolExecutor

_LOGGER = get_logger(__name__)


def _field(item: Any, name: str, default: Any = None) -> Any:
    """Read a field from an SDK model or a plain dict."""
    if isinstance(item, dict):
        return item.get(name, default)
    value = getattr(item, name, None)
    return default if value is None else value


def response_text(outputs: Any) -> str:
    """Concatenate the text of the message items of a response."""
    parts: list[str] = []
    for item in outputs or []:
        if _field(item, "type") not in ("message", None):
            continue
        content = _field(item, "content")
        if isinstance(content, str):
            parts.append(content)
            continue
        for chunk in content or []:
            if _field(chunk, "type") in ("output_text", "text") and (text := _field(chunk, "text")):
                parts.append(str(text))
    return "".join(parts)


def pending_calls(outputs: Any) -> list[PendingCall]:
    """Collect the function calls a response asks for."""
    calls: list[PendingCall] = []
    for item in outputs or []:
        if _field(item, "type") != "function_call":
            continue
        calls.append(
            PendingCall(
                tool_call_id=str(_field(item, "call_id") or _field(item, "id") or ""),
                name=str(_field(item, "name") or ""),
                arguments=_field(item, "arguments") or "",
            )
        )
    return calls


def chat_log_to_input(chat_log: Any) -> list[dict[str, Any]]:
    """Rebuild the Responses ``input`` from the Home Assistant chat log.

    The system prompt is skipped: it travels as ``instructions``. Reasoning items
    have no slot in the chat log, so they are not carried across turns.
    """
    items: list[dict[str, Any]] = []
    for content in getattr(chat_log, "content", None) or []:
        role = getattr(content, "role", None)
        text = getattr(content, "content", None)

        if role == "user":
            if text:
                items.append({"role": "user", "content": text})

        elif role == "assistant":
            if text:
                items.append({"role": "assistant", "content": text})
            for call in getattr(content, "tool_calls", None) or []:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": getattr(call, "id", "") or "",
                        "name": getattr(call, "tool_name", "") or "",
                        "arguments": json.dumps(
                            getattr(call, "tool_args", None) or {}, ensure_ascii=False, default=str
                        ),
                    }
                )

        elif role == "tool_result":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": getattr(content, "tool_call_id", "") or "",
                    "output": json.dumps(getattr(content, "tool_result", None), ensure_ascii=False, default=str),
                }
            )

    return items


class ResponsesTurnRunner:
    """Run HomeStral turns against the Mistral Responses API."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: Any,
        *,
        tool_executor: HAToolExecutor | None = None,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._client = client
        self._tool_executor = tool_executor or HAToolExecutor(hass)

    def forget(self, ha_conversation_id: str | None) -> None:
        """No server-side conversation to drop — the history lives in the chat log."""

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    def _confirm_sensitive(self) -> bool:
        return bool(get_option(self._entry, CONF_CONFIRM_SENSITIVE, DEFAULT_CONFIRM_SENSITIVE))

    def _max_iterations(self) -> int:
        return int(get_option(self._entry, CONF_MAX_TOOL_ITERATIONS, DEFAULT_MAX_TOOL_ITERATIONS))

    async def _create(
        self, *, input_items: list[dict[str, Any]], tools: list[dict[str, Any]], instructions: str, stream: bool
    ) -> Any:
        """One Responses request carrying the full history."""
        return await self._client.responses.create_async(
            model=resolve_chat_model(get_option(self._entry, CONF_MODEL)),
            input=input_items,
            instructions=instructions,
            tools=tools,
            stream=stream,
            # A stable prefix (instructions + tools + early history) is cached server-side,
            # which is what makes resending the history on every turn affordable.
            prompt_cache_key=self._entry.entry_id,
        )

    # ------------------------------------------------------------------
    # Non-streaming turn (HomestralQuery intent, one-shot)
    # ------------------------------------------------------------------

    async def async_answer(self, text: str, *, ha_conversation_id: str | None = None) -> str:
        """Send one user message and return the model's final text answer."""
        instructions = await build_ha_context(self.hass)
        legacy = bool(get_option(self._entry, CONF_LEGACY_TOOLS, DEFAULT_LEGACY_TOOLS))
        source = ALL_TOOLS if legacy else [t for t in ALL_TOOLS if t not in HA_FUNCTION_TOOLS]
        tools = to_responses_tools(source)
        router = ToolRouter(None, self._tool_executor, legacy_tools=legacy)

        items: list[dict[str, Any]] = [{"role": "user", "content": text}]
        for iteration in range(self._max_iterations()):
            response = await self._create(input_items=items, tools=tools, instructions=instructions, stream=False)
            outputs = _field(response, "output") or []
            if not outputs:
                return NO_RESPONSE_MESSAGE

            calls = pending_calls(outputs)
            _LOGGER.info(f"[RESP iter={iteration}] {len(outputs)} output items, {len(calls)} function calls")
            if not calls:
                return response_text(outputs) or NO_ANSWER_MESSAGE

            if answer := response_text(outputs):
                items.append({"role": "assistant", "content": answer})
            for index, call in enumerate(calls):
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call.tool_call_id or f"call_{index}",
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                )
                call_id, payload, _delta = await run_tool_call(
                    call, index, router, None, confirm_sensitive=self._confirm_sensitive()
                )
                items.append({"type": "function_call_output", "call_id": call_id, "output": payload})

        return TOO_MANY_STEPS_MESSAGE

    # ------------------------------------------------------------------
    # Streaming turn (conversation entity)
    # ------------------------------------------------------------------

    async def async_run_streaming(self, chat_log: Any, user_input: Any) -> None:
        """Run one turn, streaming the answer into the Home Assistant chat log."""
        await provide_llm_data(self.hass, self._entry, chat_log, user_input)
        llm_api = getattr(chat_log, "llm_api", None)
        legacy_tools = bool(get_option(self._entry, CONF_LEGACY_TOOLS, DEFAULT_LEGACY_TOOLS))
        # web_search=False: the Responses API has no built-in server-side tools.
        tools = to_responses_tools(
            build_tools(llm_api, legacy_tools=legacy_tools, web_search=False, executor=self._tool_executor)
        )
        router = ToolRouter(llm_api, self._tool_executor, legacy_tools=legacy_tools)
        agent_id = getattr(user_input, "agent_id", None) or self._entry.entry_id

        for iteration in range(self._max_iterations()):
            # The chat log already holds this turn's earlier tool calls and results, so the
            # next request is simply a re-read of it.
            input_items = chat_log_to_input(chat_log)
            _LOGGER.info(f"[RESP stream iter={iteration}] {len(input_items)} input items")
            stream = await self._create(
                input_items=input_items,
                tools=tools,
                instructions=instructions_from_chat_log(chat_log),
                stream=True,
            )
            executed: list[str] = []
            async for _content in chat_log.async_add_delta_content_stream(
                agent_id, self._transform(stream, router, executed, chat_log)
            ):
                pass
            if not executed:
                return

        _LOGGER.warning("[RESP stream] tool loop bound reached")

    async def _transform(
        self,
        stream: Any,
        router: ToolRouter,
        executed: list[str],
        chat_log: Any = None,
    ) -> AsyncGenerator[dict[str, Any]]:
        """Map Responses stream events onto Home Assistant chat-log deltas."""
        pending: list[PendingCall] = []
        started = False

        async for event in iter_stream(stream):
            kind = event_type(event)
            data = event_data(event)

            if kind == "response.output_text.delta":
                if not started:
                    started = True
                    yield {"role": "assistant"}
                if text := _field(data, "delta") or _field(data, "text"):
                    yield {"content": str(text)}

            elif kind in ("response.completed", "response.incomplete"):
                if kind == "response.incomplete":
                    # Usually the max_output_tokens cut; keep what arrived and end the turn.
                    _LOGGER.warning("[RESP stream] response incomplete")
                pending = pending_calls(_field(_field(data, "response") or data, "output"))
                break

            elif kind in ("response.failed", "error"):
                detail = _field(data, "message") or _field(_field(data, "error") or {}, "message") or str(data)
                raise HomeAssistantError(f"Mistral responses error: {detail}")

        if not pending:
            return

        if not started:
            yield {"role": "assistant"}
        yield {
            "tool_calls": [
                llm.ToolInput(
                    id=call.tool_call_id or f"call_{index}",
                    tool_name=call.name,
                    tool_args=safe_args(call.arguments),
                    external=True,
                )
                for index, call in enumerate(pending)
            ]
        }
        for index, call in enumerate(pending):
            call_id, _payload, delta = await run_tool_call(
                call, index, router, chat_log, confirm_sensitive=self._confirm_sensitive()
            )
            executed.append(call_id)
            yield delta
