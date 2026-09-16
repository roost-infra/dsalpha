"""Regression tests for the WeChat reply extraction.

The rule these pin was learned the hard way: the first implementation sent the
model's whole thinking process to WeChat, because it kept every ``content``
field that was not ``reasoning_signal``. Reasoning reaches the client under two
other spellings, and the ``tools`` agent reports results as ``text`` too.
"""

from __future__ import annotations

import json

from src.gateway.wechat.channel import extract_reply


def frame(**fields) -> list[str]:
    """One SSE frame: the event-name line, then the data line."""
    event = fields.pop("_event")
    return [f"event: {event}", "data: " + json.dumps(fields, ensure_ascii=False)]


def test_reasoning_is_never_sent() -> None:
    """Both reasoning spellings stay out of the reply."""
    lines = [
        *frame(_event="reasoning_signal", content="start"),
        *frame(_event="reasoning_content", content="Let me think about this."),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning", content="Let me"),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning", content=" think."),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning_signal", content="complete"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="答案。"),
    ]
    reply, err = extract_reply(lines)
    assert err is None
    assert reply == "答案。"
    for leaked in ("Let me", "think about this"):
        assert leaked not in reply


def test_tool_results_are_not_sent() -> None:
    """The tools agent reports content_type 'text'; it is not an answer."""
    lines = [
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="先查一下。"),
        *frame(_event="message_chunk", agent="tools", content_type="text",
               content="<raw tool output>", tool_call_id="call_1", status="success"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="结论。"),
    ]
    reply, _ = extract_reply(lines)
    assert "raw tool output" not in reply


def test_reply_is_what_follows_the_last_tool_call() -> None:
    """Pre-tool narration is commentary; the reply comes after the last result."""
    lines = [
        *frame(_event="message_chunk", agent="model:a", content_type="text",
               content="Let me search the vault for that."),
        *frame(_event="tool_calls", tool_calls=[{"name": "search_knowledge_base"}]),
        *frame(_event="tool_call_result", content="ok"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="知识库里"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="有 6 条命中。"),
    ]
    reply, _ = extract_reply(lines)
    assert reply == "知识库里有 6 条命中。"
    assert "Let me search" not in reply


def test_error_frame_is_reported_not_sent_as_reply() -> None:
    lines = [
        *frame(_event="error", error="ANTHROPIC_API_KEY environment variable is not set"),
    ]
    reply, err = extract_reply(lines)
    assert reply == ""
    assert err and "ANTHROPIC" in err


def test_no_text_at_all_is_an_empty_reply() -> None:
    """A turn that only reasoned must not produce a partial message."""
    lines = [
        *frame(_event="metadata", run_id="r1"),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning", content="hmm"),
        *frame(_event="run_end", outcome="success"),
    ]
    reply, err = extract_reply(lines)
    assert reply == ""
    assert err is None
