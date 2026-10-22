"""Tests for the shared MistralTurnRunner (agent.py).

The runner owns the Mistral Conversations API calls and the bounded tool loop
for both entry points. Real SDK entry models are used (``mistralai.client.models``
is the canonical import path of the pinned SDK).
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mistralai.client.models import FunctionCallEntry, FunctionResultEntry, MessageOutputEntry, ToolExecutionEntry

from custom_components.homestral import agent as agent_mod
from custom_components.homestral.agent import (
    CONVERSATION_TTL,
    NO_ANSWER_MESSAGE,
    NO_RESPONSE_MESSAGE,
    NO_SEARCH_RESULT_MESSAGE,
    TOO_MANY_STEPS_MESSAGE,
    UNEXPECTED_OUTPUT_MESSAGE,
    MistralTurnRunner,
    extract_text,
)
from custom_components.homestral.const import CONF_AGENT_ID, CONF_MAX_TOOL_ITERATIONS, CONF_MODEL, CONF_USE_AGENT
from custom_components.homestral.tools import ALL_TOOLS


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _response(conversation_id, *outputs):
    return SimpleNamespace(conversation_id=conversation_id, outputs=list(outputs))


def _make_runner(entry_data=None, clock=None):
    entry = MagicMock()
    entry.data = entry_data if entry_data is not None else {"api_key": "k", CONF_USE_AGENT: False}
    entry.options = {}
    client = MagicMock()
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=json.dumps({"success": True}))
    runner = MistralTurnRunner(MagicMock(), entry, client, tool_executor=executor, clock=clock or FakeClock())
    return runner, client, executor


def _ctx():
    return patch.object(agent_mod, "build_ha_context", new_callable=AsyncMock, return_value="ctx")


@pytest.mark.asyncio
async def test_first_turn_starts_conversation_with_model_tools_and_instructions():
    runner, client, _ = _make_runner()
    client.beta.conversations.start_async = AsyncMock(
        return_value=_response("conv_1", MessageOutputEntry(content="Salut"))
    )

    with _ctx():
        answer = await runner.async_answer("Bonjour", ha_conversation_id="ha_1")

    assert answer == "Salut"
    kwargs = client.beta.conversations.start_async.call_args.kwargs
    assert kwargs == {"inputs": "Bonjour", "instructions": "ctx", "tools": ALL_TOOLS, "model": "mistral-small-latest"}
    assert runner.mistral_conversation_id("ha_1") == "conv_1"


@pytest.mark.asyncio
async def test_legacy_model_id_is_resolved_before_the_call():
    runner, client, _ = _make_runner({"api_key": "k", CONF_USE_AGENT: False, CONF_MODEL: "mistral-large-4"})
    client.beta.conversations.start_async = AsyncMock(return_value=_response("c", MessageOutputEntry(content="ok")))

    with _ctx():
        await runner.async_answer("Bonjour")

    assert client.beta.conversations.start_async.call_args.kwargs["model"] == "mistral-large-latest"


@pytest.mark.asyncio
async def test_agent_mode_sends_agent_id_instead_of_model():
    runner, client, _ = _make_runner({"api_key": "k", CONF_USE_AGENT: True, CONF_AGENT_ID: "agent_42"})
    client.beta.conversations.start_async = AsyncMock(return_value=_response("c", MessageOutputEntry(content="ok")))

    with _ctx():
        await runner.async_answer("Bonjour")

    kwargs = client.beta.conversations.start_async.call_args.kwargs
    assert kwargs["agent_id"] == "agent_42"
    assert "model" not in kwargs


@pytest.mark.asyncio
async def test_second_turn_appends_to_the_same_mistral_conversation():
    runner, client, _ = _make_runner()
    client.beta.conversations.start_async = AsyncMock(return_value=_response("conv_1", MessageOutputEntry(content="a")))
    client.beta.conversations.append_async = AsyncMock(
        return_value=_response("conv_1", MessageOutputEntry(content="b"))
    )

    with _ctx():
        await runner.async_answer("Un", ha_conversation_id="ha_1")
        answer = await runner.async_answer("Deux", ha_conversation_id="ha_1")

    assert answer == "b"
    client.beta.conversations.start_async.assert_called_once()
    kwargs = client.beta.conversations.append_async.call_args.kwargs
    assert kwargs == {"conversation_id": "conv_1", "inputs": "Deux", "completion_args": {"instructions": "ctx"}}


@pytest.mark.asyncio
async def test_two_ha_conversations_get_two_mistral_conversations():
    runner, client, _ = _make_runner()
    client.beta.conversations.start_async = AsyncMock(
        side_effect=[
            _response("conv_a", MessageOutputEntry(content="a")),
            _response("conv_b", MessageOutputEntry(content="b")),
        ]
    )
    client.beta.conversations.append_async = AsyncMock()

    with _ctx():
        await runner.async_answer("salon", ha_conversation_id="user_a")
        await runner.async_answer("cuisine", ha_conversation_id="user_b")

    assert client.beta.conversations.start_async.call_count == 2
    client.beta.conversations.append_async.assert_not_called()
    assert runner.mistral_conversation_id("user_a") == "conv_a"
    assert runner.mistral_conversation_id("user_b") == "conv_b"


@pytest.mark.asyncio
async def test_one_shot_turns_are_never_remembered():
    runner, client, _ = _make_runner()
    client.beta.conversations.start_async = AsyncMock(return_value=_response("conv_x", MessageOutputEntry(content="x")))
    client.beta.conversations.append_async = AsyncMock()

    with _ctx():
        await runner.async_answer("Quelle heure ?")
        await runner.async_answer("Quelle heure ?")

    assert client.beta.conversations.start_async.call_count == 2
    client.beta.conversations.append_async.assert_not_called()
    assert runner.mistral_conversation_id(None) is None


@pytest.mark.asyncio
async def test_conversation_expires_after_ttl():
    clock = FakeClock()
    runner, client, _ = _make_runner(clock=clock)
    client.beta.conversations.start_async = AsyncMock(return_value=_response("conv_1", MessageOutputEntry(content="a")))
    client.beta.conversations.append_async = AsyncMock(
        return_value=_response("conv_1", MessageOutputEntry(content="b"))
    )

    with _ctx():
        await runner.async_answer("Un", ha_conversation_id="ha_1")
        clock.now += CONVERSATION_TTL - 1
        await runner.async_answer("Deux", ha_conversation_id="ha_1")  # still alive -> append
        clock.now += CONVERSATION_TTL + 1
        await runner.async_answer("Trois", ha_conversation_id="ha_1")  # expired -> start again

    assert client.beta.conversations.start_async.call_count == 2
    assert client.beta.conversations.append_async.call_count == 1


@pytest.mark.asyncio
async def test_batched_function_calls_are_all_executed_and_returned_together():
    runner, client, executor = _make_runner()
    calls = [
        FunctionCallEntry(tool_call_id="c1", name="control_ha_device", arguments=json.dumps({"entity_id": "light.a"})),
        FunctionCallEntry(tool_call_id="c2", name="get_ha_state", arguments=json.dumps({"entity_id": "light.b"})),
    ]
    client.beta.conversations.start_async = AsyncMock(return_value=_response("conv_1", *calls))
    client.beta.conversations.append_async = AsyncMock(
        return_value=_response("conv_1", MessageOutputEntry(content="Fait."))
    )

    with _ctx():
        answer = await runner.async_answer("Allume a et b", ha_conversation_id="ha_1")

    assert answer == "Fait."
    assert executor.execute.call_args_list[0].args == ("control_ha_device", {"entity_id": "light.a"})
    assert executor.execute.call_args_list[1].args == ("get_ha_state", {"entity_id": "light.b"})
    results = client.beta.conversations.append_async.call_args.kwargs["inputs"]
    assert [r.tool_call_id for r in results] == ["c1", "c2"]
    assert all(isinstance(r, FunctionResultEntry) for r in results)
    assert json.loads(results[0].result) == {"success": True}


@pytest.mark.asyncio
async def test_executor_exception_is_sent_back_as_error_result():
    runner, client, executor = _make_runner()
    executor.execute = AsyncMock(side_effect=RuntimeError("boom"))
    client.beta.conversations.start_async = AsyncMock(
        return_value=_response("conv_1", FunctionCallEntry(tool_call_id="c1", name="get_ha_weather", arguments="{}"))
    )
    client.beta.conversations.append_async = AsyncMock(
        return_value=_response("conv_1", MessageOutputEntry(content="Désolé."))
    )

    with _ctx():
        answer = await runner.async_answer("Météo ?")

    assert answer == "Désolé."
    results = client.beta.conversations.append_async.call_args.kwargs["inputs"]
    assert json.loads(results[0].result) == {"error": "boom"}


@pytest.mark.asyncio
async def test_builtin_tool_returns_following_message_without_append():
    runner, client, executor = _make_runner()
    client.beta.conversations.start_async = AsyncMock(
        return_value=_response(
            "conv_1",
            ToolExecutionEntry(name="web_search", arguments="{}"),
            MessageOutputEntry(content="Il fait beau."),
        )
    )
    client.beta.conversations.append_async = AsyncMock()

    with _ctx():
        answer = await runner.async_answer("Météo à Paris ?")

    assert answer == "Il fait beau."
    executor.execute.assert_not_called()
    client.beta.conversations.append_async.assert_not_called()


@pytest.mark.asyncio
async def test_builtin_tool_without_message_returns_no_result_message():
    runner, client, _ = _make_runner()
    client.beta.conversations.start_async = AsyncMock(
        return_value=_response("conv_1", ToolExecutionEntry(name="web_search", arguments="{}"))
    )

    with _ctx():
        assert await runner.async_answer("?") == NO_SEARCH_RESULT_MESSAGE


@pytest.mark.asyncio
async def test_fallback_messages_for_empty_unknown_and_blank_outputs():
    runner, client, _ = _make_runner()
    client.beta.conversations.start_async = AsyncMock(
        side_effect=[
            _response("c1"),
            _response("c2", object()),
            _response("c3", MessageOutputEntry(content="")),
        ]
    )

    with _ctx():
        assert await runner.async_answer("a") == NO_RESPONSE_MESSAGE
        assert await runner.async_answer("b") == UNEXPECTED_OUTPUT_MESSAGE
        assert await runner.async_answer("c") == NO_ANSWER_MESSAGE


@pytest.mark.asyncio
async def test_tool_loop_is_bounded_by_the_option():
    runner, client, executor = _make_runner({"api_key": "k", CONF_USE_AGENT: False, CONF_MAX_TOOL_ITERATIONS: 2})
    endless = _response("conv_1", FunctionCallEntry(tool_call_id="c1", name="get_ha_weather", arguments="{}"))
    client.beta.conversations.start_async = AsyncMock(return_value=endless)
    client.beta.conversations.append_async = AsyncMock(return_value=endless)

    with _ctx():
        answer = await runner.async_answer("Boucle", ha_conversation_id="ha_1")

    assert answer == TOO_MANY_STEPS_MESSAGE
    assert executor.execute.call_count == 2
    assert client.beta.conversations.append_async.call_count == 2


@pytest.mark.asyncio
async def test_api_error_forgets_the_conversation_and_propagates():
    runner, client, _ = _make_runner()
    runner._remember("ha_1", "existing_conv")
    client.beta.conversations.append_async = AsyncMock(side_effect=RuntimeError("API down"))

    with _ctx(), pytest.raises(RuntimeError, match="API down"):
        await runner.async_answer("Encore", ha_conversation_id="ha_1")

    assert runner.mistral_conversation_id("ha_1") is None


def test_extract_text_handles_str_chunks_and_citations():
    text_chunk = SimpleNamespace(type="text", text="Il fait ")
    citation = SimpleNamespace(type="tool_reference", title="source")
    untyped = SimpleNamespace(text="beau.")
    assert extract_text("abc") == "abc"
    assert extract_text([text_chunk, citation, untyped]) == "Il fait beau."
    assert extract_text(42) == "42"
