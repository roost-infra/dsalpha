"""LangAlpha SSE frames → AG-UI events.

The whole of the protocol *policy* lives here, as a state machine over
``(event_name, payload)`` pairs rather than over a socket. That is what makes
the rules pinnable against recorded streams without a server, a sandbox or a
model — the same reason ``extract_reply`` in the WeChat gateway is pure over
lines. Decoding the stream itself is ``sse.py``'s job.

Four rules carry the weight, each of them learned from what the stream actually
contains rather than from what its name suggests:

- **Reasoning is thinking, never answer text.** It rides ``message_chunk`` with
  ``content_type: 'reasoning'`` (deltas) and ``'reasoning_signal'`` (the
  start/complete lifecycle). The bare ``reasoning_content`` / ``reasoning_signal``
  *event names* are a second spelling of the same thing; both are accepted, but
  never both for one delta, or the scratchpad renders twice.
- **A tool result is emitted once.** The ``tools`` agent re-reports tool output
  as ``message_chunk`` with ``content_type: 'text'``. Taking that as well as
  ``tool_call_result`` duplicates every tool card in the client.
- **An agent switch, or a tool call, splits the message.** Subagents stream
  interleaved with the main model, so text from a different ``agent`` closes the
  open message instead of concatenating two speakers into one bubble.
- **An unrecognized frame degrades to ``RAW``.** This adapter is a view of the
  stream, and a view that silently hides what it does not understand is worse
  than one that shows it plainly.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from src.gateway.agui import events as ev
from src.gateway.agui.sse import (
    CUSTOM_EVENTS,
    IGNORED,
    as_text,
    error_message,
    parse_sse,
)

__all__ = ["Translator"]

# ``agent`` values are namespaced ("model:gpt-5", "tools", "task:<id>"). Only
# the model namespace is speaking to the user.
_TEXT_AGENT_PREFIX = "model:"


class Translator:
    """Turns one turn's frames into AG-UI events.

    Stateful only in the ways a stream is: which message is open, which tool
    calls have been announced, whether the run has terminated. Nothing here
    knows about HTTP, threads or users, which is what lets a recorded stream be
    replayed through it in a test.
    """

    def __init__(self, thread_id: str, run_id: str) -> None:
        self.thread_id = thread_id
        self.run_id = run_id
        self._text_id: str | None = None
        self._text_agent = ""
        self._message_seq = 0
        self._thinking_open = False
        self._thinking_text_open = False
        self._tools: dict[str, str] = {}
        self._terminal = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> list[dict[str, Any]]:
        """The opening event, emitted before the upstream stream is dialled."""
        return [ev.run_started(self.thread_id, self.run_id)]

    def close(self) -> list[dict[str, Any]]:
        """Close whatever is open and finish the run. Idempotent.

        The wire has no terminal frame — nothing emits ``finish`` and there is
        no sentinel — so the end of the response body *is* the completion
        signal, and this is where it becomes one. A run that already failed is
        already terminal and produces nothing here.
        """
        if self._terminal:
            return []
        self._terminal = True
        return [*self._close_all(), ev.run_finished(self.thread_id, self.run_id)]

    def abort(self, message: str, code: str | None = None) -> list[dict[str, Any]]:
        """Terminate the run with an error. Idempotent."""
        if self._terminal:
            return []
        self._terminal = True
        return [*self._close_all(), ev.run_error(message, code=code)]

    # ── frames ───────────────────────────────────────────────────────────

    def feed(self, event_name: str, frame: dict[str, Any]) -> list[dict[str, Any]]:
        """One upstream frame in, zero or more AG-UI events out."""
        if event_name in IGNORED:
            return []
        if event_name in ("reasoning_content", "reasoning_signal"):
            return self._feed_reasoning(event_name, frame)
        if event_name == "message_chunk":
            return self._feed_message_chunk(frame)
        if event_name in ("tool_calls", "tool_call_chunks"):
            return self._feed_tool_calls(event_name, frame)
        if event_name == "tool_call_result":
            return self._feed_tool_result(frame)
        if event_name == "error":
            return self.abort(
                error_message(frame), code=as_text(frame.get("error_type")) or None
            )
        if event_name in CUSTOM_EVENTS:
            return [ev.custom(CUSTOM_EVENTS[event_name], frame)]
        return [ev.raw(frame, source=event_name or "unknown")]

    def feed_lines(self, lines: Iterable[str]) -> list[dict[str, Any]]:
        """Parse one SSE block and feed every frame in it."""
        out: list[dict[str, Any]] = []
        for event_name, frame in parse_sse(lines):
            out.extend(self.feed(event_name, frame))
        return out

    # ── reasoning ────────────────────────────────────────────────────────

    def _feed_reasoning(
        self, event_name: str, frame: dict[str, Any]
    ) -> list[dict[str, Any]]:
        # As a bare event name, ``reasoning_signal`` carries the lifecycle; as a
        # ``content_type`` it rides inside a message_chunk and lands in
        # ``_feed_message_chunk`` instead. Both spellings reach one handler.
        if event_name == "reasoning_signal":
            return self._reasoning_signal(frame)
        delta = frame.get("content")
        if not isinstance(delta, str) or not delta:
            return []
        return [*self._open_thinking(), ev.thinking_text_message_content(delta)]

    def _reasoning_signal(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        if str(frame.get("content")) == "complete":
            return self._close_thinking()
        return self._open_thinking()

    def _open_thinking(self) -> list[dict[str, Any]]:
        """Open the thinking block and its text message, on first use."""
        out: list[dict[str, Any]] = []
        if not self._thinking_open:
            out.append(ev.thinking_start())
            self._thinking_open = True
        if not self._thinking_text_open:
            out.append(ev.thinking_text_message_start())
            self._thinking_text_open = True
        return out

    def _close_thinking(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._thinking_text_open:
            out.append(ev.thinking_text_message_end())
            self._thinking_text_open = False
        if self._thinking_open:
            out.append(ev.thinking_end())
            self._thinking_open = False
        return out

    # ── assistant text ───────────────────────────────────────────────────

    def _feed_message_chunk(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        content_type = frame.get("content_type")
        if content_type == "reasoning":
            delta = frame.get("content")
            if not isinstance(delta, str) or not delta:
                return []
            return [*self._open_thinking(), ev.thinking_text_message_content(delta)]
        if content_type == "reasoning_signal":
            return self._reasoning_signal(frame)
        if content_type != "text":
            # ``reasoning_signal`` aside, anything else here is an internal
            # marker with no client-visible meaning.
            return []

        content = frame.get("content")
        if not isinstance(content, str) or not content:
            return []
        agent = str(frame.get("agent") or "")
        if frame.get("tool_call_id"):
            # The ``tools`` agent reporting its own output. The canonical copy
            # arrives as ``tool_call_result``, so taking this as well doubles it.
            return []
        if agent.startswith(_TEXT_AGENT_PREFIX):
            return [*self._close_thinking(), *self._text_delta(agent, content)]
        # A subagent's narration is not the assistant's answer, so it goes out
        # as a custom event rather than into the user's transcript.
        return [ev.custom("langalpha.agent_text", {"agent": agent, "content": content})]

    def _text_delta(self, agent: str, delta: str) -> list[dict[str, Any]]:
        """Append to the open message, opening a new one on a speaker change."""
        out: list[dict[str, Any]] = []
        if self._text_id is None or self._text_agent != agent:
            out.extend(self._close_text())
            self._message_seq += 1
            self._text_id = f"{self.run_id}:{self._message_seq}"
            self._text_agent = agent
            out.append(ev.text_message_start(self._text_id))
        out.append(ev.text_message_content(self._text_id, delta))
        return out

    def _close_text(self) -> list[dict[str, Any]]:
        if self._text_id is None:
            return []
        message_id, self._text_id, self._text_agent = self._text_id, None, ""
        return [ev.text_message_end(message_id)]

    # ── tool calls ───────────────────────────────────────────────────────

    def _feed_tool_calls(
        self, event_name: str, frame: dict[str, Any]
    ) -> list[dict[str, Any]]:
        key = "tool_calls" if event_name == "tool_calls" else "tool_call_chunks"
        chunks = frame.get(key)
        if not isinstance(chunks, list):
            return []
        out: list[dict[str, Any]] = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            tool_call_id = str(chunk.get("id") or "")
            if not tool_call_id:
                continue
            # A tool call ends the assistant's text: what follows a result is a
            # new message, not a continuation of the narration before it.
            out.extend(self._close_text())
            out.extend(self._close_thinking())
            out.extend(self._announce_tool(tool_call_id, chunk.get("name")))
            args = chunk.get("args")
            if isinstance(args, str):
                if args:
                    out.append(ev.tool_call_args(tool_call_id, args))
            elif isinstance(args, dict) and args:
                out.append(
                    ev.tool_call_args(tool_call_id, json.dumps(args, ensure_ascii=False))
                )
        return out

    def _announce_tool(self, tool_call_id: str, name: Any) -> list[dict[str, Any]]:
        """Emit ``TOOL_CALL_START`` once per id.

        A chunked tool call carries the name only on its first chunk, so an
        unnamed continuation is not an error — it is the normal shape, and the
        name announced the first time is the one that stands.
        """
        if tool_call_id in self._tools:
            return []
        self._tools[tool_call_id] = str(name or "unknown")
        return [ev.tool_call_start(tool_call_id, self._tools[tool_call_id])]

    def _feed_tool_result(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        tool_call_id = str(frame.get("tool_call_id") or "")
        if not tool_call_id:
            return [ev.raw(frame, source="tool_call_result")]
        return [
            *self._close_tool(tool_call_id),
            ev.tool_call_result(tool_call_id, as_text(frame.get("content"))),
        ]

    def _close_tool(self, tool_call_id: str) -> list[dict[str, Any]]:
        if self._tools.pop(tool_call_id, None) is None:
            return []
        return [ev.tool_call_end(tool_call_id)]

    # ── teardown ─────────────────────────────────────────────────────────

    def _close_all(self) -> list[dict[str, Any]]:
        """Close every open block, in the order they were opened."""
        out = self._close_thinking()
        out.extend(self._close_text())
        for tool_call_id in list(self._tools):
            out.extend(self._close_tool(tool_call_id))
        return out
