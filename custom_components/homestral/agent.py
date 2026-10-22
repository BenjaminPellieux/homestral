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

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from mistralai.client.models import FunctionCallEntry, FunctionResultEntry, MessageOutputEntry, ToolExecutionEntry

from .const import (
    CONF_AGENT_ID,
    CONF_MAX_TOOL_ITERATIONS,
    CONF_MODEL,
    CONF_USE_AGENT,
    DEFAULT_MAX_TOOL_ITERATIONS,
    resolve_chat_model,
)
from .helpers import get_option
from .logging_config import get_logger
from .tools import ALL_TOOLS, HAToolExecutor, build_ha_context

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
