"""Inbound AG-UI payloads — exactly what an AG-UI client POSTs to start a run.

Only the *request* half of the protocol is modelled here. The outbound half
lives in ``events.py`` as plain dicts, because events are written far more
often than they are read, are never validated, and gain a type every few minor
versions — a dict builder that stamps ``type`` keeps a new event a one-line
addition instead of a class plus a union member plus a discriminator.

Field names are the protocol's (camelCase) and are *generated* from the Python
spelling rather than hand-written, so a field can be added in Python's own
style without anyone having to remember which of the two names goes on the
wire.

``extra="allow"`` is load-bearing rather than laziness: AG-UI is versioned by
addition, and a client one minor ahead of this server must not collect a 422
for a field we have simply never heard of.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

__all__ = [
    "AguiMessage",
    "AguiRole",
    "AguiTool",
    "AguiToolCall",
    "AguiToolCallFunction",
    "RunAgentInput",
]

AguiRole = Literal["developer", "system", "assistant", "user", "tool"]


class _CamelModel(BaseModel):
    """Protocol payloads: snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )


class AguiToolCallFunction(_CamelModel):
    name: str
    arguments: str = "{}"


class AguiToolCall(_CamelModel):
    id: str
    type: Literal["function"] = "function"
    function: AguiToolCallFunction


class AguiMessage(_CamelModel):
    """One transcript entry. ``content`` is optional because a tool-calling
    assistant turn legitimately carries only ``tool_calls``."""

    id: str | None = None
    role: AguiRole
    content: str | None = None
    name: str | None = None
    tool_calls: list[AguiToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class AguiTool(_CamelModel):
    """A client-declared tool.

    Parsed and forwarded to no one. This gateway's tools come from the agent
    configuration, and letting a request body redefine them would be a way to
    reach past that; accepting the field keeps a client that declares tools
    from being rejected, and ignoring it keeps the agent's reach unchanged.
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class RunAgentInput(_CamelModel):
    """The body of one run.

    ``thread_id`` is honoured as *this server's* thread id — see
    ``channel.AguiChannel._ensure_thread`` for why that is the honest mapping —
    and ``forwarded_props`` is the protocol's own escape hatch for
    backend-specific options, which is where ``workspaceId`` and ``agentMode``
    are read from.
    """

    thread_id: str
    run_id: str
    messages: list[AguiMessage] = Field(default_factory=list)
    tools: list[AguiTool] = Field(default_factory=list)
    state: dict[str, Any] | None = None
    parent_run_id: str | None = None
    forwarded_props: dict[str, Any] = Field(default_factory=dict)
