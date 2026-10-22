"""
End-to-end scenarios driven through MistralConversationEntity.

The entity streams the answer into the Home Assistant chat log, and the model
acts through the Home Assistant LLM API (``assist``): these tests script the
Mistral conversation events and assert on what reaches the chat log and which
Home Assistant tools were executed.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from conftest import (
    FakeChatLog,
    FakeLLMApi,
    FakeTool,
    call_event,
    done_event,
    error_event,
    make_streaming_client,
    make_user_input,
    started_event,
    text_event,
    tool_execution_event,
)
from homeassistant.exceptions import HomeAssistantError

from custom_components.homestral.agent import HomestralRuntime, MistralTurnRunner
from custom_components.homestral.const import CONF_LEGACY_TOOLS, CONF_MAX_TOOL_ITERATIONS

HA_CONVERSATION_ID = "ha_conv_001"


def _build_entity(client, entry_data=None, options=None):
    """Create a MistralConversationEntity with a scripted streaming client."""
    from custom_components.homestral.conversation import MistralConversationEntity

    mock_hass = MagicMock()
    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = options or {}
    mock_entry.data = entry_data if entry_data is not None else {"api_key": "test", "use_agent": False}
    mock_entry.runtime_data = HomestralRuntime(client=client, runner=MistralTurnRunner(mock_hass, mock_entry, client))
    return MistralConversationEntity(mock_hass, mock_entry)


def _patch_result_helper():
    return patch(
        "custom_components.homestral.conversation.conversation.async_get_result_from_chat_log",
        return_value=MagicMock(),
    )


async def _run(entity, chat_log, text="Allume la lumière du salon", conversation_id=HA_CONVERSATION_ID):
    with _patch_result_helper():
        await entity._async_handle_message(make_user_input(text, conversation_id), chat_log)


@pytest.mark.asyncio
async def test_plain_answer_streams_into_the_chat_log():
    """A text-only answer reaches the chat log in deltas, with no tool call."""
    client = make_streaming_client(
        [started_event("conv_1"), text_event("Bonjour, "), text_event("je vous écoute."), done_event()]
    )
    entity = _build_entity(client)
    chat_log = FakeChatLog(FakeLLMApi())

    await _run(entity, chat_log, "Bonjour")

    assert chat_log.text == "Bonjour, je vous écoute."
    assert chat_log.roles[0] == "assistant"
    assert chat_log.tool_calls == []
    client.beta.conversations.append_stream_async.assert_not_called()


@pytest.mark.asyncio
async def test_turn_on_light_runs_the_home_assistant_tool_and_answers():
    """The model asks for HassTurnOn, Home Assistant executes it, the answer follows."""
    client = make_streaming_client(
        [started_event("conv_1"), call_event("HassTurnOn", json.dumps({"name": "lumière du salon"})), done_event()],
        [started_event("conv_1"), text_event("J'ai allumé la lumière du salon."), done_event()],
    )
    llm_api = FakeLLMApi(result={"speech": {"plain": {"speech": "Allumé"}}})
    entity = _build_entity(client)
    chat_log = FakeChatLog(llm_api)

    await _run(entity, chat_log)

    # The tool went through the Home Assistant LLM API, not HomeStral's executor
    assert [call.tool_name for call in llm_api.calls] == ["HassTurnOn"]
    assert llm_api.calls[0].tool_args == {"name": "lumière du salon"}
    # The chat log shows the call, its result and the final text
    assert [call.tool_name for call in chat_log.tool_calls] == ["HassTurnOn"]
    assert chat_log.tool_results[0]["tool_name"] == "HassTurnOn"
    assert chat_log.text == "J'ai allumé la lumière du salon."
    # The result was sent back to Mistral on the second request
    second = client.stream_calls[1]
    assert second["conversation_id"] == "conv_1"
    assert [entry.tool_call_id for entry in second["inputs"]] == ["call_1"]


@pytest.mark.asyncio
async def test_two_tools_in_one_turn_are_both_executed():
    """ "Ferme les volets et mets le chauffage à 19" — both calls run in the same turn."""
    client = make_streaming_client(
        [
            started_event("conv_2"),
            call_event("HassTurnOff", json.dumps({"name": "volets"}), tool_call_id="call_a", output_index=0),
            call_event(
                "HassClimateSetTemperature",
                json.dumps({"temperature": 19}),
                tool_call_id="call_b",
                output_index=1,
            ),
            done_event(),
        ],
        [started_event("conv_2"), text_event("C'est fait."), done_event()],
    )
    llm_api = FakeLLMApi(tools=[FakeTool("HassTurnOff"), FakeTool("HassClimateSetTemperature")])
    entity = _build_entity(client)
    chat_log = FakeChatLog(llm_api)

    await _run(entity, chat_log, "Ferme les volets et mets le chauffage à 19")

    assert [call.tool_name for call in llm_api.calls] == ["HassTurnOff", "HassClimateSetTemperature"]
    assert len(chat_log.tool_results) == 2
    assert [entry.tool_call_id for entry in client.stream_calls[1]["inputs"]] == ["call_a", "call_b"]
    assert chat_log.text == "C'est fait."


@pytest.mark.asyncio
async def test_incremental_tool_arguments_are_accumulated():
    """Arguments split across several events are reassembled before execution."""
    client = make_streaming_client(
        [
            started_event("conv_3"),
            call_event("HassTurnOn", '{"name": "lum', tool_call_id="call_1"),
            call_event("", 'ière du salon"}', tool_call_id="call_1"),
            done_event(),
        ],
        [started_event("conv_3"), text_event("Allumé."), done_event()],
    )
    llm_api = FakeLLMApi()
    entity = _build_entity(client)
    chat_log = FakeChatLog(llm_api)

    await _run(entity, chat_log)

    assert llm_api.calls[0].tool_args == {"name": "lumière du salon"}
    assert llm_api.calls[0].tool_name == "HassTurnOn"


@pytest.mark.asyncio
async def test_server_side_web_search_is_mirrored_without_local_execution():
    """A Mistral-run tool (web search) appears in the log but is not executed locally."""
    client = make_streaming_client(
        [
            started_event("conv_4"),
            tool_execution_event("web_search"),
            text_event("Il fait beau à Paris."),
            done_event(),
        ]
    )
    llm_api = FakeLLMApi()
    entity = _build_entity(client)
    chat_log = FakeChatLog(llm_api)

    await _run(entity, chat_log, "Quel temps fait-il à Paris ?")

    assert llm_api.calls == []
    assert [call.tool_name for call in chat_log.tool_calls] == ["web_search"]
    assert all(call.external for call in chat_log.tool_calls)
    assert chat_log.text == "Il fait beau à Paris."
    client.beta.conversations.append_stream_async.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_as_an_error_result():
    """With legacy tools off, a HomeStral-only tool name is refused, not executed."""
    client = make_streaming_client(
        [
            started_event("conv_5"),
            call_event("control_ha_device", json.dumps({"entity_id": "lock.porte"})),
            done_event(),
        ],
        [started_event("conv_5"), text_event("Je ne peux pas faire cela."), done_event()],
    )
    llm_api = FakeLLMApi()
    entity = _build_entity(client, options={CONF_LEGACY_TOOLS: False})
    chat_log = FakeChatLog(llm_api)

    await _run(entity, chat_log)

    assert llm_api.calls == []
    assert "error" in chat_log.tool_results[0]["tool_result"]
    assert json.loads(client.stream_calls[1]["inputs"][0].result)["error"]


@pytest.mark.asyncio
async def test_legacy_tools_still_run_when_the_option_is_on():
    """Migrated entries keep HomeStral's own tools working."""
    client = make_streaming_client(
        [
            started_event("conv_6"),
            call_event("control_ha_device", json.dumps({"entity_id": "light.salon", "command": "turn_on"})),
            done_event(),
        ],
        [started_event("conv_6"), text_event("Allumé."), done_event()],
    )
    entity = _build_entity(client, options={CONF_LEGACY_TOOLS: True})
    chat_log = FakeChatLog(FakeLLMApi())

    with patch.object(entity._runner._tool_executor, "execute", return_value=json.dumps({"success": True})) as executor:
        executor.return_value = json.dumps({"success": True})
        await _run(entity, chat_log)

    executor.assert_called_once_with("control_ha_device", {"entity_id": "light.salon", "command": "turn_on"})
    assert chat_log.tool_results[0]["tool_result"] == {"success": True}


@pytest.mark.asyncio
async def test_api_error_event_becomes_a_chat_log_error_and_resets_the_conversation():
    client = make_streaming_client([started_event("conv_7"), error_event("quota exceeded"), done_event()])
    entity = _build_entity(client)
    chat_log = FakeChatLog(FakeLLMApi())

    await _run(entity, chat_log)

    # Internal error details are NOT leaked to the user — only a generic message.
    assert "Désolé, une erreur est survenue" in chat_log.content[-1].content
    assert "quota exceeded" not in chat_log.content[-1].content
    assert entity._runner.mistral_conversation_id(HA_CONVERSATION_ID) is None


@pytest.mark.asyncio
async def test_tool_loop_is_bounded():
    """A model that keeps calling tools is stopped at the configured bound."""
    endless = [started_event("conv_8"), call_event("HassTurnOn", "{}"), done_event()]
    client = make_streaming_client(endless, endless, endless, endless)
    entity = _build_entity(client, options={CONF_MAX_TOOL_ITERATIONS: 2})
    chat_log = FakeChatLog(FakeLLMApi())

    await _run(entity, chat_log)

    assert client.beta.conversations.start_stream_async.call_count == 1
    assert client.beta.conversations.append_stream_async.call_count == 1  # 2 iterations total


@pytest.mark.asyncio
async def test_second_turn_appends_to_the_same_mistral_conversation():
    client = make_streaming_client(
        [started_event("conv_9"), text_event("Bonjour."), done_event()],
        [started_event("conv_9"), text_event("Il fait beau."), done_event()],
    )
    entity = _build_entity(client)

    await _run(entity, FakeChatLog(FakeLLMApi()), "Bonjour")
    second_log = FakeChatLog(FakeLLMApi())
    await _run(entity, second_log, "Et la météo ?")

    client.beta.conversations.start_stream_async.assert_called_once()
    assert client.stream_calls[1]["conversation_id"] == "conv_9"
    assert second_log.text == "Il fait beau."


@pytest.mark.asyncio
async def test_two_satellites_do_not_share_a_mistral_conversation():
    client = make_streaming_client(
        [started_event("conv_salon"), text_event("Salon ok."), done_event()],
        [started_event("conv_cuisine"), text_event("Cuisine ok."), done_event()],
    )
    entity = _build_entity(client)

    await _run(entity, FakeChatLog(FakeLLMApi()), "Allume le salon", "sat_salon")
    await _run(entity, FakeChatLog(FakeLLMApi()), "Allume la cuisine", "sat_cuisine")

    assert client.beta.conversations.start_stream_async.call_count == 2
    client.beta.conversations.append_stream_async.assert_not_called()
    assert entity._runner.mistral_conversation_id("sat_salon") == "conv_salon"
    assert entity._runner.mistral_conversation_id("sat_cuisine") == "conv_cuisine"


@pytest.mark.asyncio
async def test_runner_raises_home_assistant_error_on_stream_error():
    """The runner itself surfaces a HomeAssistantError (the entity catches it)."""
    client = make_streaming_client([started_event("conv_a"), error_event("boom"), done_event()])
    entity = _build_entity(client)

    with pytest.raises(HomeAssistantError, match="boom"):
        await entity._runner.async_run_streaming(FakeChatLog(FakeLLMApi()), make_user_input())


if __name__ == "__main__":
    pytest.main([__file__])
