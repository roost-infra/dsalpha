"""AG-UI gateway: exposes the agent to AG-UI clients over one SSE endpoint.

AG-UI is the protocol agent frontends speak — a client POSTs a run and reads a
stream of typed events. This package is the adapter, and it owns no agent, no
thread and no state: it accepts a run, drives it through the app's own HTTP API,
and re-expresses the resulting frames in AG-UI's vocabulary.

Unlike the WeChat channel there is no poll loop and no binding to persist, so
importing this package never opens a socket and there is nothing to start or
stop — the whole gateway is request-scoped.
"""

from __future__ import annotations

import os

from src.gateway.agui.channel import AguiChannel
from src.gateway.agui.models import AguiMessage, AguiTool, RunAgentInput
from src.gateway.agui.sse import parse_sse
from src.gateway.agui.translate import Translator

__all__ = [
    "AguiChannel",
    "AguiMessage",
    "AguiTool",
    "RunAgentInput",
    "Translator",
    "enabled",
    "parse_sse",
]


def enabled() -> bool:
    """Whether the AG-UI routes serve.

    Off by default. This is an external protocol surface, and on an ``oss``
    deployment the app resolves every caller to the same local user — so
    exposing it should be a deliberate act rather than something a deploy does
    by being upgraded.

    Read at call time, not import time: the router registers unconditionally so
    that flipping the flag is a restart-free change of behavior rather than a
    different route table.
    """
    return os.environ.get("AGUI_ENABLED", "").strip().lower() in ("1", "true", "yes")
