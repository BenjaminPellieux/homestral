"""Shared Mistral turn runner.

One ``MistralTurnRunner`` per config entry runs a HomeStral turn against the
Mistral Conversations API for both entry points, the conversation entity and
the ``HomestralQuery`` intent: start or append a server-side conversation,
execute the Home Assistant function tools the model asks for (bounded loop)
and return the final text.

Mistral conversations are tracked per Home Assistant ``conversation_id`` so
users, devices and satellites never share one thread.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator, AsyncIterable, Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from mistralai.client.models import FunctionCallEntry, FunctionResultEntry, MessageOutputEntry, ToolExecutionEntry

from .const import (
    CONF_AGENT_ID,
    CONF_CONFIRM_SENSITIVE,
    CONF_LEGACY_TOOLS,
    CONF_LLM_HASS_API,
    CONF_MAX_TOOL_ITERATIONS,
    CONF_MODEL,
    CONF_PROMPT,
    CONF_USE_AGENT,
    DEFAULT_CONFIRM_SENSITIVE,
    DEFAULT_LEGACY_TOOLS,
    DEFAULT_LLM_HASS_API,
    DEFAULT_MAX_TOOL_ITERATIONS,
    DEFAULT_PROMPT,
    DOMAIN,
    resolve_chat_model,
)
from .context_builder import build_ha_context
from .helpers import get_option
from .llm_tools import ToolRouter, build_tools
from .logging_config import get_logger
from .safety import guard
from .tools import ALL_TOOLS, HAToolExecutor

_LOGGER = get_logger(__name__)

NO_RESPONSE_MESSAGE = "Désolé, je n'ai pas reçu de réponse."
NO_SEARCH_RESULT_MESSAGE = "La recherche n'a pas retourné de résultat."
UNEXPECTED_OUTPUT_MESSAGE = "Réponse inattendue du modèle."
TOO_MANY_STEPS_MESSAGE = "La réponse a nécessité trop d'étapes. Veuillez reformuler."
NO_ANSWER_MESSAGE = "Aucune réponse disponible."

# A Mistral conversation that has not been used for this long is dropped; the next turn
# of that HA conversation starts a fresh one (same order of magnitude as HA chat sessions).
CONVERSATION_TTL = 30 * 60


def extract_text(content: Any) -> str:
    """Extract plain text from a Mistral content field.

    Handles str, list[TextChunk], and mixed lists that may contain ToolReference
    objects (web_search citations). Only TextChunk items (type='text') are kept.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for chunk in content:
            chunk_type = getattr(chunk, "type", None)
            if chunk_type == "text" or (chunk_type is None and hasattr(chunk, "text")):
                parts.append(chunk.text)
            # ToolReference (type='tool_reference') and other non-text chunks are skipped
        return "".join(parts)
    return str(content)


@dataclass
class _ConversationRef:
    mistral_id: str
    last_used: float


@dataclass
class _PendingCall:
    """A function call being assembled from one or more ``function.call.delta`` events."""

    tool_call_id: str
    name: str
    arguments: str = ""


def event_type(event: Any) -> str | None:
    """The ``type`` of a conversation stream event, whether or not the SDK wraps it in ``data``."""
    data = getattr(event, "data", None)
    return getattr(data, "type", None) or getattr(event, "type", None)


def event_data(event: Any) -> Any:
    """The payload of a conversation stream event."""
    data = getattr(event, "data", None)
    return data if data is not None else event


class MistralTurnRunner:
    """Run HomeStral turns against the Mistral Conversations API."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: Any,
        *,
        tool_executor: HAToolExecutor | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._client = client
        self._tool_executor = tool_executor or HAToolExecutor(hass)
        self._clock = clock
        self._conversations: dict[str, _ConversationRef] = {}

    # ------------------------------------------------------------------
    # Per-HA-conversation state
    # ------------------------------------------------------------------

    def mistral_conversation_id(self, ha_conversation_id: str | None) -> str | None:
        """Return the live Mistral conversation bound to an HA conversation, if any."""
        if ha_conversation_id is None:
            return None
        self._expire()
        ref = self._conversations.get(ha_conversation_id)
        return ref.mistral_id if ref else None

    def forget(self, ha_conversation_id: str | None) -> None:
        """Drop the Mistral conversation bound to an HA conversation."""
        if ha_conversation_id is not None:
            self._conversations.pop(ha_conversation_id, None)

    def _remember(self, ha_conversation_id: str | None, mistral_id: str | None) -> None:
        if ha_conversation_id is None or not isinstance(mistral_id, str) or not mistral_id:
            return
        self._conversations[ha_conversation_id] = _ConversationRef(mistral_id, self._clock())

    def _expire(self) -> None:
        now = self._clock()
        for key in [k for k, ref in self._conversations.items() if now - ref.last_used > CONVERSATION_TTL]:
            del self._conversations[key]

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    async def async_answer(self, text: str, *, ha_conversation_id: str | None = None) -> str:
        """Send one user message and return the model's final text answer.

        ``ha_conversation_id`` binds the turn to a Mistral conversation; ``None``
        runs a one-shot turn (used by the HomestralQuery intent).
        """
        instructions = await build_ha_context(self.hass)
        mistral_id = self.mistral_conversation_id(ha_conversation_id)
        _LOGGER.info(f"[CONV] new message, ha_conversation_id={ha_conversation_id!r}, mistral_id={mistral_id!r}")
        try:
            if mistral_id is None:
                response = await self._start(text, instructions)
            else:
                _LOGGER.info("Continuing conversation")
                response = await self._client.beta.conversations.append_async(
                    conversation_id=mistral_id,
                    inputs=text,
                    completion_args={"instructions": instructions},
                )
            mistral_id = getattr(response, "conversation_id", None) or mistral_id
            self._remember(ha_conversation_id, mistral_id)
            content = await self._run_tool_loop(response, mistral_id, ha_conversation_id)
        except Exception:
            self.forget(ha_conversation_id)
            raise
        _LOGGER.info(f"[CONV] final content: {content[:200]}")
        return content

    async def _start(self, text: str, instructions: str) -> Any:
        kwargs: dict[str, Any] = dict(inputs=text, instructions=instructions, tools=ALL_TOOLS)
        if get_option(self._entry, CONF_USE_AGENT, False):
            _LOGGER.info("Starting new conversation with agent")
            kwargs["agent_id"] = get_option(self._entry, CONF_AGENT_ID)
        else:
            _LOGGER.info("Starting new conversation with model")
            kwargs["model"] = resolve_chat_model(get_option(self._entry, CONF_MODEL))
        return await self._client.beta.conversations.start_async(**kwargs)

    async def _run_tool_loop(self, response: Any, mistral_id: str | None, ha_conversation_id: str | None) -> str:
        """Execute function calls until the model answers with text (bounded by the option)."""
        max_iterations = int(get_option(self._entry, CONF_MAX_TOOL_ITERATIONS, DEFAULT_MAX_TOOL_ITERATIONS))
        for iteration in range(max_iterations):
            if not response.outputs:
                return NO_RESPONSE_MESSAGE

            first = response.outputs[0]
            _LOGGER.info(f"[TOOL LOOP iter={iteration}] output type: {type(first).__name__}")

            if isinstance(first, ToolExecutionEntry):
                # Built-in Mistral server-side tool (web_search, code_interpreter, etc.)
                _LOGGER.info(f"[TOOL built-in] {first.name}, args: {first.arguments}")
                for out in response.outputs[1:]:
                    if isinstance(out, MessageOutputEntry):
                        return extract_text(out.content) or NO_ANSWER_MESSAGE
                return NO_SEARCH_RESULT_MESSAGE

            if isinstance(first, FunctionCallEntry):
                # Collect ALL function calls — Mistral may batch several in one response.
                # Sending only the first result causes HTTP 400 "missing function results".
                calls = [o for o in response.outputs if isinstance(o, FunctionCallEntry)]
                results = await self._execute_calls(calls)
                response = await self._client.beta.conversations.append_async(
                    conversation_id=mistral_id,
                    inputs=results,
                )
                mistral_id = getattr(response, "conversation_id", None) or mistral_id
                self._remember(ha_conversation_id, mistral_id)
                continue

            if isinstance(first, MessageOutputEntry):
                return extract_text(first.content) or NO_ANSWER_MESSAGE

            _LOGGER.warning(f"[TOOL LOOP] unknown output type: {type(first)}")
            return UNEXPECTED_OUTPUT_MESSAGE

        return TOO_MANY_STEPS_MESSAGE

    # ------------------------------------------------------------------
    # Streaming turn (conversation entity)
    # ------------------------------------------------------------------

    async def async_run_streaming(self, chat_log: Any, user_input: Any) -> None:
        """Run one turn, streaming the answer into the Home Assistant chat log.

        Tools come from the Home Assistant LLM API (``assist`` by default), so the
        model acts through Home Assistant's own intents: the exposure settings and
        the area of the speaking satellite are honoured.
        """
        ha_conversation_id = getattr(user_input, "conversation_id", None)
        await self._async_provide_llm_data(chat_log, user_input)
        llm_api = getattr(chat_log, "llm_api", None)
        legacy_tools = bool(get_option(self._entry, CONF_LEGACY_TOOLS, DEFAULT_LEGACY_TOOLS))
        tools = build_tools(llm_api, legacy_tools=legacy_tools)
        router = ToolRouter(llm_api, self._tool_executor, legacy_tools=legacy_tools)

        mistral_id = self.mistral_conversation_id(ha_conversation_id)
        inputs: Any = user_input.text
        max_iterations = int(get_option(self._entry, CONF_MAX_TOOL_ITERATIONS, DEFAULT_MAX_TOOL_ITERATIONS))

        try:
            for iteration in range(max_iterations):
                _LOGGER.info(f"[CONV stream iter={iteration}] mistral_id={mistral_id!r}")
                stream = await self._open_stream(inputs, mistral_id, tools, chat_log)
                results: list[Any] = []
                async for _content in chat_log.async_add_delta_content_stream(
                    self._agent_id(user_input),
                    self._transform(stream, router, results, ha_conversation_id, chat_log),
                ):
                    pass
                mistral_id = self.mistral_conversation_id(ha_conversation_id) or mistral_id
                if not results:
                    return
                inputs = results
        except HomeAssistantError:
            self.forget(ha_conversation_id)
            raise
        except Exception:
            self.forget(ha_conversation_id)
            raise
        _LOGGER.warning("[CONV stream] tool loop bound reached")

    def _agent_id(self, user_input: Any) -> str:
        return getattr(user_input, "agent_id", None) or self._entry.entry_id

    async def _async_provide_llm_data(self, chat_log: Any, user_input: Any) -> None:
        """Let Home Assistant build the system prompt and resolve the LLM API."""
        api_option = get_option(self._entry, CONF_LLM_HASS_API, DEFAULT_LLM_HASS_API)
        apis = [api_option] if isinstance(api_option, str) else list(api_option or [])
        prompt = str(get_option(self._entry, CONF_PROMPT, DEFAULT_PROMPT) or "").strip()
        if not prompt:
            legacy_tools = bool(get_option(self._entry, CONF_LEGACY_TOOLS, DEFAULT_LEGACY_TOOLS))
            prompt = await build_ha_context(self.hass, legacy_tools=legacy_tools)
        await chat_log.async_provide_llm_data(
            user_input.as_llm_context(DOMAIN),
            apis or None,
            prompt,
            getattr(user_input, "extra_system_prompt", None),
        )

    async def _open_stream(self, inputs: Any, mistral_id: str | None, tools: list[Any], chat_log: Any) -> Any:
        """Start or continue the Mistral conversation in streaming mode."""
        instructions = self._instructions(chat_log)
        if mistral_id is None:
            kwargs: dict[str, Any] = dict(inputs=inputs, instructions=instructions, tools=tools)
            if get_option(self._entry, CONF_USE_AGENT, False):
                kwargs["agent_id"] = get_option(self._entry, CONF_AGENT_ID)
            else:
                kwargs["model"] = resolve_chat_model(get_option(self._entry, CONF_MODEL))
            return await self._client.beta.conversations.start_stream_async(**kwargs)
        return await self._client.beta.conversations.append_stream_async(
            conversation_id=mistral_id,
            inputs=inputs,
            completion_args={"instructions": instructions},
        )

    @staticmethod
    def _instructions(chat_log: Any) -> str:
        """The system prompt Home Assistant assembled (first SystemContent of the log)."""
        content = getattr(chat_log, "content", None) or []
        first = content[0] if content else None
        return getattr(first, "content", "") or ""

    async def _transform(
        self,
        stream: Any,
        router: ToolRouter,
        results: list[Any],
        ha_conversation_id: str | None,
        chat_log: Any = None,
    ) -> AsyncGenerator[dict[str, Any]]:
        """Map Mistral conversation events onto Home Assistant chat-log deltas.

        Function-call arguments may arrive complete in one event or in pieces, so
        they are accumulated per ``output_index`` and executed once the response is
        done; the results are collected for the next request of the tool loop.
        """
        pending: dict[int, _PendingCall] = {}
        started = False

        async for event in self._iter_stream(stream):
            kind = event_type(event)
            data = event_data(event)

            if kind == "conversation.response.started":
                self._remember(ha_conversation_id, getattr(data, "conversation_id", None))
                if not started:
                    started = True
                    yield {"role": "assistant"}

            elif kind == "message.output.delta":
                if not started:
                    started = True
                    yield {"role": "assistant"}
                if text := extract_text(getattr(data, "content", "")):
                    yield {"content": text}

            elif kind == "function.call.delta":
                index = getattr(data, "output_index", 0) or 0
                call = pending.get(index)
                if call is None:
                    pending[index] = _PendingCall(
                        tool_call_id=getattr(data, "tool_call_id", "") or getattr(data, "id", ""),
                        name=getattr(data, "name", "") or "",
                        arguments=getattr(data, "arguments", "") or "",
                    )
                else:
                    call.arguments += getattr(data, "arguments", "") or ""
                    call.name = call.name or (getattr(data, "name", "") or "")

            elif kind in ("tool.execution.started", "tool.execution.done"):
                # Server-side tool (web search): Mistral runs it, we only mirror it in the log.
                if kind == "tool.execution.done":
                    name = getattr(data, "name", "tool") or "tool"
                    call_id = getattr(data, "id", "") or name
                    if not started:
                        started = True
                        yield {"role": "assistant"}
                    yield {
                        "tool_calls": [
                            llm.ToolInput(
                                id=call_id,
                                tool_name=name,
                                tool_args=self._safe_args(getattr(data, "arguments", "")),
                                external=True,
                            )
                        ]
                    }
                    yield {
                        "role": "tool_result",
                        "tool_call_id": call_id,
                        "tool_name": name,
                        "tool_result": {"status": "done"},
                    }

            elif kind == "conversation.response.error":
                message = getattr(data, "message", None) or str(data)
                raise HomeAssistantError(f"Mistral conversation error: {message}")

            elif kind == "conversation.response.done":
                break

        for delta in self._execute_pending(pending, router, results, started, chat_log):
            started = True
            yield await delta if asyncio.iscoroutine(delta) else delta

    @staticmethod
    async def _iter_stream(stream: Any) -> AsyncIterable[Any]:
        """Iterate a stream that may or may not be an async context manager."""
        if hasattr(stream, "__aenter__"):
            async with stream as events:
                async for event in events:
                    yield event
        else:
            async for event in stream:
                yield event

    @staticmethod
    def _safe_args(arguments: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) and arguments else arguments
        except ValueError:
            return {"raw": str(arguments)}
        return parsed if isinstance(parsed, dict) else {"raw": str(arguments)}

    def _execute_pending(
        self,
        pending: dict[int, _PendingCall],
        router: ToolRouter,
        results: list[Any],
        started: bool,
        chat_log: Any = None,
    ) -> list[Any]:
        """Build the delta sequence that reports and executes the collected calls."""
        if not pending:
            return []
        calls = [pending[index] for index in sorted(pending)]
        deltas: list[Any] = []
        if not started:
            deltas.append({"role": "assistant"})
        deltas.append(
            {
                "tool_calls": [
                    llm.ToolInput(
                        id=call.tool_call_id or f"call_{index}",
                        tool_name=call.name,
                        tool_args=self._safe_args(call.arguments),
                        external=True,
                    )
                    for index, call in enumerate(calls)
                ]
            }
        )
        for index, call in enumerate(calls):
            deltas.append(self._run_and_report(call, index, router, results, chat_log))
        return deltas

    async def _run_and_report(
        self,
        call: _PendingCall,
        index: int,
        router: ToolRouter,
        results: list[Any],
        chat_log: Any = None,
    ) -> dict:
        """Execute one call, record its result for the next request and report it to the log."""
        _LOGGER.info(f"[TOOL stream] {call.name}, args: {call.arguments[:200]}")
        refusal = guard(
            call.name,
            self._safe_args(call.arguments),
            chat_log,
            enabled=bool(get_option(self._entry, CONF_CONFIRM_SENSITIVE, DEFAULT_CONFIRM_SENSITIVE)),
        )
        result = refusal if refusal is not None else await router.async_call(call.name, call.arguments)
        payload = json.dumps(result, ensure_ascii=False, default=str)
        call_id = call.tool_call_id or f"call_{index}"
        results.append(FunctionResultEntry(tool_call_id=call_id, result=payload))
        return {
            "role": "tool_result",
            "tool_call_id": call_id,
            "tool_name": call.name,
            "tool_result": result if isinstance(result, dict) else {"result": result},
        }

    async def _execute_calls(self, calls: list[Any]) -> list[Any]:
        results = []
        for call in calls:
            args_str = call.arguments if isinstance(call.arguments, str) else json.dumps(call.arguments)
            _LOGGER.info(f"[TOOL custom] {call.name}, args: {args_str}")
            try:
                tool_result = await self._tool_executor.execute(call.name, json.loads(args_str or "{}"))
            except Exception as exc:
                _LOGGER.error(f"[TOOL error] {call.name}: {exc}")
                tool_result = json.dumps({"error": str(exc)})
            _LOGGER.info(f"[TOOL result] {call.name}: {tool_result[:200]}")
            results.append(FunctionResultEntry(tool_call_id=call.tool_call_id, result=tool_result))
        return results


@dataclass
class HomestralRuntime:
    """What a config entry keeps at runtime (``entry.runtime_data``)."""

    client: Any
    runner: MistralTurnRunner
    cache: dict[str, Any] = field(default_factory=dict)
