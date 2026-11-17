# The Mistral Responses API in HomeStral — analysis and design

**Status:** implemented as an opt-in experimental backend (option `chat_backend = responses`).
The default stays the Conversations API. Analysis dated **2026-10-29**, against the Responses
API public preview and the `mistralai` SDK **3.6.0**.

## Why this document

HomeStral has always run its chat on Mistral's **Conversations API**
(`client.beta.conversations.*`), which keeps the thread server-side. Mistral's newer
[Responses API](https://docs.mistral.ai/studio/conversations/responses) exposes the
OpenAI-compatible Responses format. Adopting it is therefore not "adding memory" — it is
**moving from a stateful API to a stateless one**, which trades a set of features for a
different set. This file records what was measured, what the trade is, and how the backend is
built, so the choice does not have to be re-derived.

## Verified facts

Measured from the official documentation page and by inspecting the 3.6.0 wheel, not inferred:

| Fact | Evidence |
| --- | --- |
| Stateless, history resent every turn | SDK docstring: *"For multi-turn conversations, send the full history in input, including prior output items and function results. Responses are not stored."* |
| Client-executed function tools only | Same docstring; the request tool union is `ResponsesFunctionTool \| ResponsesNamespaceTool` |
| Flat tool shape | `ResponsesFunctionTool` fields are `{type: "function", name, description, parameters, strict, ...}` — not nested under `function` as `FunctionTool` is |
| Absent from the previously pinned SDK | `client.responses` does not exist in 3.3.0; it appears in 3.6.0 (`mistralai/client/responses.py`) |
| Parameters gained | `temperature`, `top_p`, `max_output_tokens`, `reasoning.effort`, `text.format` (JSON Schema), `prompt_cache_key`, `max_tool_calls`, `previous_response_id` |
| Stream events | `response.output_text.delta`, `response.completed`, `response.failed`, `response.incomplete`, `error` |
| Token counting | `POST /v1/responses/input_tokens` |

Note that `previous_response_id` exists in the signature while the docstring states responses
are not stored; HomeStral does not rely on it.

## The trade

| Gained on the Responses backend | Lost on the Responses backend |
| --- | --- |
| History lives in the Home Assistant chat log, so it **survives a restart or a reload** | **Built-in web search** — there are no server-side tools |
| No conversation stored on Mistral's side | **Mistral agents** (`agent_id` has no equivalent) |
| Tools are re-sent every request, so a tool list can change mid-conversation | The whole history is resent every turn (tokens, latency) |
| Sampling, structured output and reasoning effort become reachable | Public preview: event names and item shapes may change |
| One less piece of server state to expire, drop on error and lose on restart | Reasoning items have no chat-log slot, so they are not carried across turns |

The Conversations API is itself a beta endpoint, so "preview instability" is a difference of
degree rather than of kind.

**Conclusion.** A straight migration would be a net loss today: it would cost web search and
agent mode, which are in use, to buy restart-survival on an API still in preview. A second,
opt-in backend buys the benefit for users who want it, costs nothing to users who do not, and
makes the eventual decision reversible — so that is what was built.

## How the backend is built

`custom_components/homestral/responses_backend.py` holds `ResponsesTurnRunner`, which presents
the same interface the conversation entity and the `HomestralQuery` intent already use
(`async_answer`, `async_run_streaming`, `forget`); `create_runner()` in `__init__.py` picks one
runner per config entry, and changing the option reloads the entry.

**History comes from the chat log.** `chat_log_to_input()` rebuilds the `input` array on every
request: user messages, assistant text, one `function_call` item per tool call and one
`function_call_output` per result; the system prompt is skipped because it travels as
`instructions`. This is the approach Home Assistant's own core LLM integrations take, and it is
what makes the context survive a restart. Within a turn it is also self-maintaining: the chat log
already holds the tool calls and results the previous iteration streamed into it, so the next
request is a re-read rather than a separate accumulator.

**Items are plain dicts, not SDK models.** The preview models will churn across SDK bumps; dicts
keep the integration on the wire contract and keep the test fakes trivial.

**Tools.** `to_responses_tools()` (in `llm_tools.py`) flattens Mistral's nested `FunctionTool`
into the Responses shape and drops anything that is not a function tool, with a warning. The
streaming path builds the list with `web_search=False`, since a built-in tool would only be
dropped. `ToolRouter` and `HAToolExecutor` are reused unchanged.

**Cost control.** Every request sets `prompt_cache_key` to the config entry id, so the stable
prefix (instructions, tools, early history) is served from Mistral's cache. This is what makes
resending the history affordable; Home Assistant's own chat-session expiry bounds how long the
log can grow.

**Shared helpers.** `PendingCall`, `safe_args`, `instructions_from_chat_log`, `iter_stream`,
`provide_llm_data` and `run_tool_call` live at module level in `agent.py` and are shared by both
runners, so the guard, the router and the chat-log delta contract have one implementation.

**Refused combination.** `use_agent` together with `chat_backend = responses` is a hard config-flow
error (`agent_requires_conversations`) rather than a silent fallback: silently switching a user
from their agent to a plain model would be worse than refusing.

## Re-evaluation triggers

Revisit making Responses the default when any of these happens:

1. The Responses API leaves public preview.
2. Built-in tools — web search above all — become available on Responses.
3. An equivalent of Mistral agents or connectors appears there.
4. `beta.conversations.*` is announced as deprecated.

Until then, Conversations stays the default and Responses stays labelled experimental.

## Open questions

- `async_answer` (the intent path) is deliberately one-shot, since `intent.py` always passes
  `ha_conversation_id=None`. If a future caller needs cross-turn memory on that path, it needs a
  local item store.
- `prompt_cache_key` is the entry id, which maximises cache sharing across conversations. A
  per-conversation key would isolate them at the cost of fewer cache hits.
- Sampling options (`temperature`, `max_output_tokens`) are reachable on this backend but are not
  exposed yet; exposing them for both backends (Conversations takes them through
  `completion_args`) is a separate change.
