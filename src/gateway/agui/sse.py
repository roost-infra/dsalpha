"""Wire-shape knowledge: what a LangAlpha SSE stream looks like on the page.

Separated from the translation rules because the two change for different
reasons. This module is about *decoding* the stream — line framing, which field
spellings exist at all, what a frame's payload may be. ``translate.py`` is about
what a decoded frame should become. A producer that renames a field lands here;
a decision about how to present reasoning does not.

The tables below are the stream's vocabulary, not a policy: what a frame *means*
to an AG-UI client is decided in ``translate.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

__all__ = [
    "CUSTOM_EVENTS",
    "IGNORED",
    "as_text",
    "error_message",
    "parse_sse",
]

# Stream events with no AG-UI vocabulary, forwarded verbatim under a namespaced
# CUSTOM event so a client can opt into the parts of the wire the protocol does
# not model (tool cards, sources, approvals, quota).
CUSTOM_EVENTS = {
    "artifact": "langalpha.artifact",
    "provenance": "langalpha.provenance",
    "interrupt": "langalpha.interrupt",
    "workflow_status": "langalpha.workflow_status",
    "credit_usage": "langalpha.credit_usage",
    "context_window": "langalpha.context_window",
    "steering_delivered": "langalpha.steering_delivered",
    "model_retry": "langalpha.model_retry",
    "model_fallback": "langalpha.model_fallback",
}

# Bookkeeping the client either already knows or has no use for. ``metadata``
# names the run, but ``RUN_STARTED`` has already gone out by the time the
# upstream stream is dialled — it has to, or a client sees nothing until the
# first token.
IGNORED = frozenset({"metadata", "user_message", "thread_created"})


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(event_name, payload)`` for each frame in ``lines``.

    The name rides its own line with no counterpart in the JSON, so it is
    carried forward the way the SSE spec says an ``event:`` field applies until
    the next one. A payload that is not a JSON object is dropped rather than
    raised: this reads a network stream, and one truncated frame must not take
    down a run that is otherwise fine.
    """
    event_name = ""
    for line in lines:
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        try:
            frame = json.loads(line[5:].strip())
        except ValueError:
            continue
        if isinstance(frame, dict):
            yield event_name, frame


def as_text(value: Any) -> str:
    """A tool payload as text, for a field the protocol types as a string.

    Non-strings are serialized rather than ``str()``'d, so a client parsing the
    content gets JSON instead of a Python repr.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def error_message(frame: dict[str, Any]) -> str:
    """The most specific message the error frame carries.

    The frame grew its fields over time — ``content``, then ``error``, then
    ``message`` — and different producers still fill different ones, so the
    order here is newest-first rather than a single field.
    """
    for key in ("error", "message", "content"):
        value = frame.get(key)
        if isinstance(value, str) and value:
            return value
    return "run failed"
