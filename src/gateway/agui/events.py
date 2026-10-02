"""Outbound AG-UI events — one constructor per type, plus SSE framing.

Constructors rather than a class per event: a payload here is built once and
read by someone else's client, so the only thing that has to be right is the
field spelling. Keeping each one a two-line function also means the full set of
event types fits on one screen, which is what makes "did we handle X?" an
answerable question rather than a grep.

Every key is camelCase on purpose — it is the protocol's spelling and goes
straight onto the wire, so there is no translation step between this file and
the client. Timestamps are deliberately absent: AG-UI makes them optional, and
a server clock is not evidence about when a client should render anything.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = [
    "custom",
    "encode",
    "messages_snapshot",
    "raw",
    "run_error",
    "run_finished",
    "run_started",
    "state_snapshot",
    "step_finished",
    "step_started",
    "text_message_content",
    "text_message_end",
    "text_message_start",
    "thinking_end",
    "thinking_start",
    "thinking_text_message_content",
    "thinking_text_message_end",
    "thinking_text_message_start",
    "tool_call_args",
    "tool_call_end",
    "tool_call_result",
    "tool_call_start",
]


def _event(type_: str, **fields: Any) -> dict[str, Any]:
    """Stamp the type onto a payload, dropping fields that carry no value.

    ``None`` is dropped rather than serialized: a client branching on
    ``parentMessageId !== undefined`` would otherwise see an explicit null and
    take the "this is a child message" path for every root message.
    """
    return {"type": type_, **{k: v for k, v in fields.items() if v is not None}}


# ── lifecycle ────────────────────────────────────────────────────────────


def run_started(
    thread_id: str, run_id: str, parent_run_id: str | None = None
) -> dict[str, Any]:
    return _event(
        "RUN_STARTED", threadId=thread_id, runId=run_id, parentRunId=parent_run_id
    )


def run_finished(
    thread_id: str, run_id: str, outcome: str = "success", result: Any = None
) -> dict[str, Any]:
    return _event(
        "RUN_FINISHED", threadId=thread_id, runId=run_id, outcome=outcome, result=result
    )


def run_error(message: str, code: str | None = None) -> dict[str, Any]:
    return _event("RUN_ERROR", message=message, code=code)


def step_started(step_name: str) -> dict[str, Any]:
    return _event("STEP_STARTED", stepName=step_name)


def step_finished(step_name: str) -> dict[str, Any]:
    return _event("STEP_FINISHED", stepName=step_name)


# ── assistant text ───────────────────────────────────────────────────────


def text_message_start(message_id: str, role: str = "assistant") -> dict[str, Any]:
    return _event("TEXT_MESSAGE_START", messageId=message_id, role=role)


def text_message_content(message_id: str, delta: str) -> dict[str, Any]:
    return _event("TEXT_MESSAGE_CONTENT", messageId=message_id, delta=delta)


def text_message_end(message_id: str) -> dict[str, Any]:
    return _event("TEXT_MESSAGE_END", messageId=message_id)


# ── thinking (reasoning) ─────────────────────────────────────────────────


def thinking_start(title: str | None = None) -> dict[str, Any]:
    return _event("THINKING_START", title=title)


def thinking_end() -> dict[str, Any]:
    return _event("THINKING_END")


def thinking_text_message_start() -> dict[str, Any]:
    return _event("THINKING_TEXT_MESSAGE_START")


def thinking_text_message_content(delta: str) -> dict[str, Any]:
    return _event("THINKING_TEXT_MESSAGE_CONTENT", delta=delta)


def thinking_text_message_end() -> dict[str, Any]:
    return _event("THINKING_TEXT_MESSAGE_END")


# ── tool calls ───────────────────────────────────────────────────────────


def tool_call_start(
    tool_call_id: str, tool_call_name: str, parent_message_id: str | None = None
) -> dict[str, Any]:
    return _event(
        "TOOL_CALL_START",
        toolCallId=tool_call_id,
        toolCallName=tool_call_name,
        parentMessageId=parent_message_id,
    )


def tool_call_args(tool_call_id: str, delta: str) -> dict[str, Any]:
    return _event("TOOL_CALL_ARGS", toolCallId=tool_call_id, delta=delta)


def tool_call_end(tool_call_id: str) -> dict[str, Any]:
    return _event("TOOL_CALL_END", toolCallId=tool_call_id)


def tool_call_result(
    tool_call_id: str, content: str, message_id: str | None = None, role: str = "tool"
) -> dict[str, Any]:
    return _event(
        "TOOL_CALL_RESULT",
        messageId=message_id or f"{tool_call_id}:result",
        toolCallId=tool_call_id,
        content=content,
        role=role,
    )


# ── state & escape hatches ───────────────────────────────────────────────


def state_snapshot(snapshot: Any) -> dict[str, Any]:
    return _event("STATE_SNAPSHOT", snapshot=snapshot)


def messages_snapshot(messages: list[dict[str, Any]]) -> dict[str, Any]:
    return _event("MESSAGES_SNAPSHOT", messages=messages)


def custom(name: str, value: Any) -> dict[str, Any]:
    return _event("CUSTOM", name=name, value=value)


def raw(event: Any, source: str | None = None) -> dict[str, Any]:
    return _event("RAW", event=event, source=source)


# ── transport ────────────────────────────────────────────────────────────


def encode(event: dict[str, Any]) -> str:
    """One AG-UI event as an SSE frame.

    The protocol puts the type *inside* the payload, so there is no ``event:``
    line — a reader that keyed off SSE event names would find every frame
    unnamed. ``default=str`` keeps an unserializable value in the frame as its
    repr instead of failing the run at the last step.
    """
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
