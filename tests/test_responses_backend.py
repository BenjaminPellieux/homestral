"""The experimental Responses backend.

Unlike the Conversations runner, this one is stateless: it rebuilds the whole
request from the Home Assistant chat log on every turn. These tests script the
Responses stream events and assert both on what reaches the chat log and on the
``input`` each request carried.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from conftest import (
    FakeChatLog,
    FakeLLMApi,
    FakeTool,
    make_responses_client,
    make_user_input,
    resp_completed,
    resp_failed,
    resp_function_call,
    resp_incomplete,
    resp_message,
    resp_text_delta,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

from custom_components.homestral.const import (
    CONF_CONFIRM_SENSITIVE,
    CONF_LEGACY_TOOLS,
    CONF_MAX_TOOL_ITERATIONS,
)
from custom_components.homestral.llm_tools import to_responses_tools
from custom_components.homestral.responses_backend import (
    ResponsesTurnRunner,
    chat_log_to_input,
    pending_calls,
    response_text,
)


def _runner(client, options=None, executor=None):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = options or {}
    entry.data = {"api_key": "test"}
    if executor is None:
        executor = MagicMock()
        executor.writable_calendars = MagicMock(return_value=False)
        executor.execute = AsyncMock(return_value=json.dumps({"ok": True}))
    return ResponsesTurnRunner(MagicMock(), entry, client, tool_executor=executor)


async def _run(runner, chat_log, text="Allume la lumière"):
    chat_log.content.append(SimpleNamespace(role="user", content=text))
    await runner.async_run_streaming(chat_log, make_user_input(text))


# ---------------------------------------------------------------------------
# chat_log_to_input
# ---------------------------------------------------------------------------


def test_chat_log_to_input_skips_the_system_prompt():
    """The system prompt travels as ``instructions``, never as an input item."""
    log = FakeChatLog(prompt="sys")
    log.content.append(SimpleNamespace(role="user", content="bonjour"))

    assert chat_log_to_input(log) == [{"role": "user", "content": "bonjour"}]


def test_chat_log_to_input_round_trips_a_tool_call():
    """An assistant turn with tool calls becomes text plus function_call items."""
    log = FakeChatLog()
    log.content += [
        SimpleNamespace(role="user", content="allume"),
        SimpleNamespace(
            role="assistant",
            content="J'allume",
            tool_calls=[llm.ToolInput(id="call_9", tool_name="HassTurnOn", tool_args={"name": "salon"})],
        ),
        SimpleNamespace(role="tool_result", tool_call_id="call_9", tool_name="HassTurnOn", tool_result={"ok": True}),
    ]

    assert chat_log_to_input(log) == [
        {"role": "user", "content": "allume"},
        {"role": "assistant", "content": "J'allume"},
        {"type": "function_call", "call_id": "call_9", "name": "HassTurnOn", "arguments": '{"name": "salon"}'},
        {"type": "function_call_output", "call_id": "call_9", "output": '{"ok": true}'},
    ]


def test_chat_log_to_input_keeps_a_tool_call_without_text():
    """A tool-only assistant turn yields the function_call item alone."""
    log = FakeChatLog()
    log.content.append(
        SimpleNamespace(
            role="assistant", content="", tool_calls=[llm.ToolInput(id="c1", tool_name="HassTurnOff", tool_args={})]
        )
    )

    assert chat_log_to_input(log) == [
        {"type": "function_call", "call_id": "c1", "name": "HassTurnOff", "arguments": "{}"}
    ]


def test_chat_log_to_input_serialises_a_non_dict_tool_result():
    """Whatever a tool returned has to survive as JSON."""
    log = FakeChatLog()
    log.content.append(SimpleNamespace(role="tool_result", tool_call_id="c1", tool_name="t", tool_result=["a", "b"]))

    assert chat_log_to_input(log) == [{"type": "function_call_output", "call_id": "c1", "output": '["a", "b"]'}]


def test_chat_log_to_input_of_an_empty_log():
    assert chat_log_to_input(SimpleNamespace(content=[])) == []


# ---------------------------------------------------------------------------
# Tool conversion and output readers
# ---------------------------------------------------------------------------


def test_to_responses_tools_flattens_function_tools():
    """Mistral's nested FunctionTool becomes the flat Responses shape."""
    from custom_components.homestral.llm_tools import ha_tool_to_mistral

    mistral_tool = ha_tool_to_mistral(FakeTool("HassTurnOn", "Turn on"))
    converted = to_responses_tools([mistral_tool])

    # The parameters schema is serialized by Home Assistant itself (voluptuous-openapi
    # on the 2026.2 floor, probatio on latest), so assert the mapping, not one
    # version's serialization.
    assert converted == [
        {
            "type": "function",
            "name": "HassTurnOn",
            "description": "Turn on",
            "parameters": mistral_tool.function.parameters,
        }
    ]


def test_to_responses_tools_drops_built_in_tools():
    """Server-side tools (web search) have no place on the Responses API."""
    from custom_components.homestral.tools import WEB_SEARCH_TOOL

    assert to_responses_tools([WEB_SEARCH_TOOL]) == []


def test_response_text_joins_message_parts():
    assert response_text([resp_message("Bon"), resp_message("jour")]) == "Bonjour"


def test_pending_calls_reads_function_call_items():
    calls = pending_calls([resp_message("x"), resp_function_call("HassTurnOn", "{}", "c7")])

    assert [(c.tool_call_id, c.name) for c in calls] == [("c7", "HassTurnOn")]


def test_function_call_arguments_done_event_tolerates_missing_name():
    """The live API omits `name` on response.function_call_arguments.done.

    mistralai 3.6/3.7 mark it required, which made stream parsing raise
    ValidationError mid-turn; responses_backend relaxes the field at import.
    """
    from mistralai.client.models.responsesfunctioncallargumentsdoneevent import (
        ResponsesFunctionCallArgumentsDoneEvent,
    )

    event = ResponsesFunctionCallArgumentsDoneEvent(
        type="response.function_call_arguments.done",
        arguments='{"domain": ["light"]}',
        item_id="fc_1",
        output_index=0,
        sequence_number=3,
    )

    assert event.name is None
    assert event.arguments == '{"domain": ["light"]}'


# ---------------------------------------------------------------------------
# Streaming turns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_answer_streams_and_sends_the_history():
    """A text-only turn makes one request carrying the log, and streams the answer."""
    client = make_responses_client([resp_text_delta("Il fait "), resp_text_delta("beau."), resp_completed()])
    log = FakeChatLog(prompt="sys prompt")

    await _run(_runner(client), log, "Quel temps fait-il ?")

    assert log.text == "Il fait beau."
    assert log.roles == ["assistant"]
    assert len(client.responses_calls) == 1
    assert client.responses_calls[0]["input"] == [{"role": "user", "content": "Quel temps fait-il ?"}]
    assert client.responses_calls[0]["instructions"] == "sys prompt"
    assert client.responses_calls[0]["prompt_cache_key"] == "test_entry"
    assert client.responses_calls[0]["stream"] is True


@pytest.mark.asyncio
async def test_tool_call_is_executed_and_the_next_request_carries_the_result():
    """The second request rebuilds the history, function_call_output included."""
    client = make_responses_client(
        [resp_text_delta("J'allume"), resp_completed(resp_function_call("HassTurnOn", '{"name": "salon"}', "c1"))],
        [resp_text_delta("C'est fait."), resp_completed()],
    )
    api = FakeLLMApi([FakeTool("HassTurnOn")])
    log = FakeChatLog(llm_api=api)

    await _run(_runner(client), log)

    assert [call.tool_name for call in api.calls] == ["HassTurnOn"]
    assert log.text == "J'allumeC'est fait."
    assert len(client.responses_calls) == 2
    assert client.responses_calls[1]["input"] == [
        {"role": "user", "content": "Allume la lumière"},
        {"role": "assistant", "content": "J'allume"},
        {"type": "function_call", "call_id": "c1", "name": "HassTurnOn", "arguments": '{"name": "salon"}'},
        {"type": "function_call_output", "call_id": "c1", "output": '{"success": true}'},
    ]


@pytest.mark.asyncio
async def test_tools_are_resent_on_every_request():
    """Tools are not frozen at conversation start the way they are on Conversations."""
    client = make_responses_client(
        [resp_completed(resp_function_call("HassTurnOn", "{}", "c1"))],
        [resp_text_delta("ok"), resp_completed()],
    )
    log = FakeChatLog(llm_api=FakeLLMApi([FakeTool("HassTurnOn")]))

    await _run(_runner(client), log)

    assert [t["name"] for t in client.responses_calls[0]["tools"]] == ["HassTurnOn"]
    assert client.responses_calls[1]["tools"] == client.responses_calls[0]["tools"]


@pytest.mark.asyncio
async def test_no_built_in_web_search_tool_is_offered():
    """build_tools is called with web_search=False on this backend."""
    client = make_responses_client([resp_text_delta("ok"), resp_completed()])
    log = FakeChatLog(llm_api=FakeLLMApi([FakeTool("HassTurnOn")]))

    await _run(_runner(client), log)

    assert all(tool["type"] == "function" for tool in client.responses_calls[0]["tools"])
    assert "web_search" not in [tool["name"] for tool in client.responses_calls[0]["tools"]]


@pytest.mark.asyncio
async def test_a_failed_response_raises():
    """The model's error text never leaks to the user, it raises for the entity."""
    client = make_responses_client([resp_text_delta("hmm"), resp_failed("quota exceeded")])

    with pytest.raises(HomeAssistantError, match="quota exceeded"):
        await _run(_runner(client), FakeChatLog())


@pytest.mark.asyncio
async def test_an_incomplete_response_ends_the_turn_cleanly():
    """A truncated answer is kept and the turn stops without raising."""
    client = make_responses_client([resp_text_delta("Il était une"), resp_incomplete()])
    log = FakeChatLog()

    await _run(_runner(client), log)

    assert log.text == "Il était une"
    assert len(client.responses_calls) == 1


@pytest.mark.asyncio
async def test_the_tool_loop_is_bounded_by_the_option():
    """A model that only ever asks for tools stops at max_tool_iterations."""
    scripts = [[resp_completed(resp_function_call("HassTurnOn", "{}", f"c{i}"))] for i in range(5)]
    client = make_responses_client(*scripts)
    log = FakeChatLog(llm_api=FakeLLMApi([FakeTool("HassTurnOn")]))

    await _run(_runner(client, options={CONF_MAX_TOOL_ITERATIONS: 3}), log)

    assert len(client.responses_calls) == 3


@pytest.mark.asyncio
async def test_a_sensitive_action_is_refused_before_execution():
    """The confirmation guard runs on this backend too."""
    client = make_responses_client(
        [resp_completed(resp_function_call("HassTurnOn", '{"name": "porte", "domain": "lock"}', "c1"))],
        [resp_text_delta("Confirmez-vous ?"), resp_completed()],
    )
    api = FakeLLMApi([FakeTool("HassTurnOn")])
    log = FakeChatLog(llm_api=api)

    await _run(_runner(client, options={CONF_CONFIRM_SENSITIVE: True}), log, "Ouvre la porte")

    assert api.calls == []
    assert "Confirmation requise" in log.tool_results[0]["tool_result"]["error"]


# ---------------------------------------------------------------------------
# One-shot turn (HomestralQuery intent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_answer_returns_the_text_of_a_one_shot_turn():
    client = make_responses_client(SimpleNamespace(output=[resp_message("Il fait 20 degrés.")]))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("custom_components.homestral.responses_backend.build_ha_context", AsyncMock(return_value="ctx"))
        answer = await _runner(client).async_answer("Quelle température ?")

    assert answer == "Il fait 20 degrés."
    assert client.responses_calls[0]["stream"] is False
    assert client.responses_calls[0]["input"] == [{"role": "user", "content": "Quelle température ?"}]


@pytest.mark.asyncio
async def test_async_answer_runs_the_tool_loop():
    """A one-shot turn keeps its own item list across tool rounds."""
    client = make_responses_client(
        SimpleNamespace(output=[resp_function_call("control_ha_device", '{"entity_id": "light.x"}', "c1")]),
        SimpleNamespace(output=[resp_message("C'est allumé.")]),
    )
    executor = MagicMock()
    executor.writable_calendars = MagicMock(return_value=False)
    executor.execute = AsyncMock(return_value=json.dumps({"ok": True}))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("custom_components.homestral.responses_backend.build_ha_context", AsyncMock(return_value="ctx"))
        answer = await _runner(client, options={CONF_LEGACY_TOOLS: True}, executor=executor).async_answer("Allume")

    assert answer == "C'est allumé."
    assert executor.execute.await_count == 1
    assert client.responses_calls[1]["input"][-1] == {
        "type": "function_call_output",
        "call_id": "c1",
        "output": '{"ok": true}',
    }


@pytest.mark.asyncio
async def test_async_answer_without_output_falls_back():
    client = make_responses_client(SimpleNamespace(output=[]))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("custom_components.homestral.responses_backend.build_ha_context", AsyncMock(return_value="ctx"))
        answer = await _runner(client).async_answer("Bonjour")

    assert "pas reçu de réponse" in answer


def test_forget_is_a_no_op():
    """There is no server-side conversation to drop."""
    runner = _runner(make_responses_client())

    assert runner.forget("ha_conv") is None
