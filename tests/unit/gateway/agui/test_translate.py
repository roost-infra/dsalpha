"""Regression tests for the AG-UI translation rules.

Every rule pinned here was a way to get the transcript wrong: reasoning leaking
into the answer, a tool card emitted twice, two speakers concatenated into one
bubble, or an unrecognized frame vanishing without trace.

The frames are hand-written from the wire shapes rather than captured, so a
producer change that alters a field name shows up as a failing translation test
instead of as a silently empty stream.
"""

from __future__ import annotations

import json
from typing import Any

from src.gateway.agui import events as ev
from src.gateway.agui.channel import _last_user_text, _options
from src.gateway.agui.models import AguiMessage, RunAgentInput
from src.gateway.agui.sse import parse_sse
from src.gateway.agui.translate import Translator

THREAD = "thread-1"
RUN = "run-1"


def frame(**fields: Any) -> list[str]:
    """One SSE frame: the event-name line, then the data line."""
    event = fields.pop("_event")
    return [f"event: {event}", "data: " + json.dumps(fields, ensure_ascii=False)]


def translate(lines: list[str]) -> list[dict[str, Any]]:
    """Replay a recorded stream through a translator, opening and closing it."""
    translator = Translator(THREAD, RUN)
    events = translator.start()
    events.extend(translator.feed_lines(lines))
    events.extend(translator.close())
    return events


def types(events: list[dict[str, Any]]) -> list[str]:
    return [event["type"] for event in events]


def deltas(events: list[dict[str, Any]], type_: str) -> str:
    return "".join(e["delta"] for e in events if e["type"] == type_)


# ── reasoning ────────────────────────────────────────────────────────────


def test_reasoning_never_becomes_answer_text() -> None:
    events = translate([
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning_signal", content="start"),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning", content="Let me think."),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning_signal", content="complete"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="答案。"),
    ])
    assert types(events) == [
        "RUN_STARTED",
        "THINKING_START",
        "THINKING_TEXT_MESSAGE_START",
        "THINKING_TEXT_MESSAGE_CONTENT",
        "THINKING_TEXT_MESSAGE_END",
        "THINKING_END",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert deltas(events, "TEXT_MESSAGE_CONTENT") == "答案。"
    # The reasoning is not dropped — it is routed to thinking, and only there.
    assert deltas(events, "THINKING_TEXT_MESSAGE_CONTENT") == "Let me think."
    assert "Let me think." not in deltas(events, "TEXT_MESSAGE_CONTENT")


def test_bare_reasoning_events_are_thinking_too() -> None:
    """The second spelling of reasoning — its own event name — is not answer text."""
    events = translate([
        *frame(_event="reasoning_signal", content="start"),
        *frame(_event="reasoning_content", content="hmm"),
        *frame(_event="reasoning_signal", content="complete"),
    ])
    assert deltas(events, "THINKING_TEXT_MESSAGE_CONTENT") == "hmm"
    assert "TEXT_MESSAGE_CONTENT" not in types(events)


def test_thinking_is_closed_before_the_answer_starts() -> None:
    """Reasoning that never sent a completion signal still must not stay open."""
    events = translate([
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning", content="thinking..."),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="answer"),
    ])
    kinds = types(events)
    assert kinds.index("THINKING_END") < kinds.index("TEXT_MESSAGE_CONTENT")


# ── tool calls ───────────────────────────────────────────────────────────


def test_tool_output_is_emitted_once() -> None:
    """The tools agent re-reports its output as text; only the result counts."""
    events = translate([
        *frame(_event="tool_calls", agent="model:a",
               tool_calls=[{"id": "c1", "name": "search", "args": {"q": "x"}}]),
        *frame(_event="message_chunk", agent="tools", content_type="text",
               content="<raw tool output>", tool_call_id="c1", status="success"),
        *frame(_event="tool_call_result", tool_call_id="c1", content="ok",
               content_type="text", status="success"),
    ])
    results = [e for e in events if e["type"] == "TOOL_CALL_RESULT"]
    assert len(results) == 1
    assert results[0]["content"] == "ok"
    assert types(events).count("TOOL_CALL_END") == 1
    assert "TEXT_MESSAGE_CONTENT" not in types(events)
    assert "raw tool output" not in json.dumps(events, ensure_ascii=False)


def test_tool_call_closes_the_message_it_interrupts() -> None:
    """Pre-tool narration is its own message; the reply starts after the result."""
    events = translate([
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="先查一下。"),
        *frame(_event="tool_calls", tool_calls=[{"id": "c1", "name": "search"}]),
        *frame(_event="tool_call_result", tool_call_id="c1", content="ok"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="结论。"),
    ])
    kinds = types(events)
    assert kinds.index("TEXT_MESSAGE_END") < kinds.index("TOOL_CALL_START")
    assert kinds.count("TEXT_MESSAGE_START") == 2
    assert deltas(events, "TEXT_MESSAGE_CONTENT") == "先查一下。结论。"


def test_chunked_tool_call_is_announced_once_and_accumulates_args() -> None:
    """The name rides only the first chunk; the rest are argument deltas."""
    events = translate([
        *frame(_event="tool_call_chunks", tool_call_chunks=[{"id": "c1", "name": "search", "args": '{"q":'}]),
        *frame(_event="tool_call_chunks", tool_call_chunks=[{"id": "c1", "args": '"x"}'}]),
    ])
    assert types(events).count("TOOL_CALL_START") == 1
    assert json.loads(deltas(events, "TOOL_CALL_ARGS")) == {"q": "x"}


def test_a_non_string_tool_result_is_serialized_not_reprd() -> None:
    """A client parsing the content should get JSON, not a Python repr."""
    events = translate([
        *frame(_event="tool_call_result", tool_call_id="c1", content={"rows": 3}),
    ])
    result = next(e for e in events if e["type"] == "TOOL_CALL_RESULT")
    assert json.loads(result["content"]) == {"rows": 3}


# ── speakers ─────────────────────────────────────────────────────────────


def test_agent_switch_splits_the_message() -> None:
    """Two interleaved speakers must not be concatenated into one bubble."""
    events = translate([
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="A"),
        *frame(_event="message_chunk", agent="model:b", content_type="text", content="B"),
    ])
    starts = [e for e in events if e["type"] == "TEXT_MESSAGE_START"]
    assert len(starts) == 2
    assert starts[0]["messageId"] != starts[1]["messageId"]
    assert types(events).count("TEXT_MESSAGE_END") == 2


def test_subagent_text_is_not_the_assistant_answer() -> None:
    events = translate([
        *frame(_event="message_chunk", agent="task:abc", content_type="text", content="子代理输出"),
    ])
    assert "TEXT_MESSAGE_CONTENT" not in types(events)
    custom = [e for e in events if e["type"] == "CUSTOM"]
    assert custom and custom[0]["name"] == "langalpha.agent_text"
    assert custom[0]["value"]["agent"] == "task:abc"


# ── pass-through ─────────────────────────────────────────────────────────


def test_unmodelled_stream_events_ride_custom() -> None:
    events = translate([
        *frame(_event="artifact", artifact_type="chart", artifact_id="a1"),
    ])
    custom = [e for e in events if e["type"] == "CUSTOM"]
    assert custom[0]["name"] == "langalpha.artifact"
    assert custom[0]["value"]["artifact_type"] == "chart"


def test_unknown_frames_degrade_to_raw() -> None:
    """A view that hides what it does not understand is worse than one that shows it."""
    events = translate([*frame(_event="brand_new_thing", payload=1)])
    raw = [e for e in events if e["type"] == "RAW"]
    assert len(raw) == 1
    assert raw[0]["source"] == "brand_new_thing"
    assert raw[0]["event"] == {"payload": 1}


# ── termination ──────────────────────────────────────────────────────────


def test_error_terminates_the_run_without_a_success() -> None:
    events = translate([*frame(_event="error", error="boom", error_type="upstream")])
    assert types(events)[-1] == "RUN_ERROR"
    assert "RUN_FINISHED" not in types(events)
    assert events[-1]["code"] == "upstream"


def test_a_stream_that_ends_mid_tool_still_closes_it() -> None:
    """EOF is the terminal signal, so a half-finished tool must not dangle."""
    events = translate([
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="working"),
        *frame(_event="tool_calls", tool_calls=[{"id": "c1", "name": "search"}]),
    ])
    kinds = types(events)
    assert kinds[-1] == "RUN_FINISHED"
    assert kinds.count("TOOL_CALL_END") == 1
    assert kinds.count("TEXT_MESSAGE_END") == 1


def test_close_is_idempotent() -> None:
    translator = Translator(THREAD, RUN)
    translator.feed_lines(
        frame(_event="message_chunk", agent="model:a", content_type="text", content="hi")
    )
    first = translator.close()
    assert types(first)[-1] == "RUN_FINISHED"
    assert translator.close() == []


def test_run_started_echoes_the_client_ids() -> None:
    assert Translator(THREAD, RUN).start() == [
        {"type": "RUN_STARTED", "threadId": THREAD, "runId": RUN}
    ]


# ── framing ──────────────────────────────────────────────────────────────


def test_parse_sse_drops_a_malformed_frame_instead_of_raising() -> None:
    lines = ["event: message_chunk", "data: {not json", "", "event: message_chunk", "data: {}"]
    assert list(parse_sse(lines)) == [("message_chunk", {})]


def test_parse_sse_carries_the_event_name_across_lines() -> None:
    """The name has no counterpart in the payload, so it must survive its line."""
    assert list(parse_sse(["id: 7", "event: x", "data: {}"])) == [("x", {})]


def test_encoded_events_are_data_only_sse_frames() -> None:
    """AG-UI puts the type in the payload, so there is no `event:` line."""
    text = ev.encode(ev.run_error("nope"))
    assert text.startswith("data: ")
    assert text.endswith("\n\n")
    assert "\nevent:" not in text
    assert json.loads(text[6:]) == {"type": "RUN_ERROR", "message": "nope"}


def test_absent_fields_are_omitted_rather_than_nulled() -> None:
    assert "parentMessageId" not in ev.tool_call_start("c1", "search")
    assert "title" not in ev.thinking_start()


# ── request mapping ──────────────────────────────────────────────────────


def test_run_input_accepts_camel_case_and_unknown_fields() -> None:
    """A client one minor ahead must not collect a 422 for a field we don't know."""
    body = RunAgentInput.model_validate({
        "threadId": "t",
        "runId": "r",
        "forwardedProps": {"agentMode": "flash"},
        "messages": [{"role": "user", "content": "hi"}],
        "somethingNew": 1,
    })
    assert body.thread_id == "t"
    assert body.forwarded_props["agentMode"] == "flash"
    assert body.messages[0].role == "user"


def test_only_the_last_user_message_is_the_prompt() -> None:
    """History is the thread's checkpoint server-side; replaying it would duplicate."""
    body = RunAgentInput(thread_id="t", run_id="r", messages=[
        AguiMessage(role="user", content="first"),
        AguiMessage(role="assistant", content="answer"),
        AguiMessage(role="user", content="  second  "),
    ])
    assert _last_user_text(body) == "second"


def test_a_run_with_no_user_message_has_no_prompt() -> None:
    body = RunAgentInput(thread_id="t", run_id="r", messages=[
        AguiMessage(role="assistant", content="x"),
    ])
    assert _last_user_text(body) == ""


def test_an_unknown_agent_mode_falls_back_to_ptc() -> None:
    body = RunAgentInput(thread_id="t", run_id="r", forwarded_props={"agentMode": "warp"})
    assert _options(body) == ("ptc", "")
    assert _options(RunAgentInput(thread_id="t", run_id="r")) == ("ptc", "")


# ── the gateway's own switch ─────────────────────────────────────────────


def test_the_gateway_is_off_until_it_is_switched_on(monkeypatch) -> None:
    """On ``oss`` every caller resolves to the same local user, so an external
    protocol surface must be opt-in rather than a side effect of upgrading."""
    from src.gateway.agui import enabled

    monkeypatch.delenv("AGUI_ENABLED", raising=False)
    assert enabled() is False
    for off in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("AGUI_ENABLED", off)
        assert enabled() is False
    for on in ("1", "true", "YES", "true"):
        monkeypatch.setenv("AGUI_ENABLED", on)
        assert enabled() is True
