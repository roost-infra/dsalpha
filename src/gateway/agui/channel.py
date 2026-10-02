"""One AG-UI run, bridged onto this app's own chat API.

A run executes by POSTing to ``/api/v1/threads/{id}/messages`` over loopback
rather than by re-entering the agent in-process — the same choice, for the same
reason, as the WeChat channel. The HTTP path already owns thread persistence,
the run ledger, sandbox provisioning, MCP tool binding and SSE streaming, and a
second entry point would re-implement all of it and drift. One loopback round
trip per run is not the expensive part of a turn.

The gateway keeps no state: there is no binding to persist and no poll loop to
supervise, because an AG-UI run is one request in, one stream out. So the
channel is request-scoped, and its lifetime is an ``async with`` block.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from typing import Any, NamedTuple

import httpx

from src.gateway.agui import events as ev
from src.gateway.agui.models import RunAgentInput
from src.gateway.agui.translate import Translator

logger = logging.getLogger(__name__)

__all__ = ["AguiChannel"]

# A research turn legitimately runs for minutes (sandbox + MCP tools).
_TURN_TIMEOUT_SEC = float(os.environ.get("AGUI_TURN_TIMEOUT_SEC", "900"))
_WORKSPACE_NAME = os.environ.get("AGUI_WORKSPACE_NAME", "AG-UI")


def _self_base_url() -> str:
    return os.environ.get("AGUI_SELF_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _options(body: RunAgentInput) -> tuple[str, str]:
    """Agent mode and workspace, read from ``forwardedProps``.

    AG-UI has no vocabulary for either, and ``forwardedProps`` is the protocol's
    own answer to that: backend-specific options ride there rather than being
    invented as top-level fields a client would have to guess at.
    """
    props = body.forwarded_props or {}
    mode = str(props.get("agentMode") or "ptc")
    if mode not in ("ptc", "flash"):
        # An unrecognized mode is not a reason to fail a run; ptc is the
        # default everywhere else in the app, so it is the default here.
        mode = "ptc"
    return mode, str(props.get("workspaceId") or "")


def _last_user_text(body: RunAgentInput) -> str:
    """The turn's prompt: the last user message the client sent.

    Only the new message is forwarded. The thread's history is authoritative
    server-side — it *is* the LangGraph checkpoint — so replaying the client's
    copy of it would duplicate rows rather than restore context.
    """
    for message in reversed(body.messages):
        content = message.content
        if message.role == "user" and isinstance(content, str) and content.strip():
            return content.strip()
    return ""


class _ThreadRef(NamedTuple):
    """The thread a run landed in, and whether this run is what created it."""

    thread_id: str
    workspace_id: str
    created: bool


class AguiChannel:
    """Bridges one AG-UI run onto the app's chat API, as the calling user."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=_TURN_TIMEOUT_SEC)
        )

    async def __aenter__(self) -> AguiChannel:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── identity ─────────────────────────────────────────────────────────

    def _loopback_headers(self) -> dict[str, str]:
        """Headers that identify this call to the app's own API.

        In ``HOST_MODE=oss`` none are needed. In ``platform`` every endpoint
        resolves a caller from a Bearer JWT, which a server-side bridge has no
        way to hold, so it authenticates as a service instead
        (``get_current_user_id`` accepts X-Service-Token + X-User-Id). The
        identity is the calling user's, so the run lands in *their* workspace
        rather than a shared one — and without this the gateway 401s the moment
        auth is switched on.
        """
        token = os.environ.get("INTERNAL_SERVICE_TOKEN", "").strip()
        if not token or not self.user_id:
            return {}
        return {"X-Service-Token": token, "X-User-Id": self.user_id}

    # ── the run ──────────────────────────────────────────────────────────

    async def run(self, body: RunAgentInput) -> AsyncIterator[str]:
        """Stream one run as encoded AG-UI SSE frames.

        Never raises: everything that can go wrong has a protocol event to say
        so, and a client that receives a ``RUN_ERROR`` can show it, where a
        dropped connection shows nothing at all.
        """
        translator = Translator(body.thread_id, body.run_id)
        for event in translator.start():
            yield ev.encode(event)

        prompt = _last_user_text(body)
        if not prompt:
            for event in translator.abort(
                "RunAgentInput carried no user message.", code="empty_input"
            ):
                yield ev.encode(event)
            return

        try:
            ref = await self._ensure_thread(body, prompt)
            if ref.created:
                # The client invented its threadId; this is the id that will
                # actually hold the conversation, so it is handed back.
                yield ev.encode(
                    ev.custom("langalpha.thread", {"threadId": ref.thread_id})
                )
            async for event in self._stream_turn(translator, ref, body, prompt):
                yield ev.encode(event)
        except Exception as exc:  # noqa: BLE001
            logger.exception("agui run failed for %s: %s", self.user_id, exc)
            # The turn's own error frames already reached the translator; this
            # covers the transport failing around them.
            for event in translator.abort(f"run failed: {exc}"):
                yield ev.encode(event)
            return

        for event in translator.close():
            yield ev.encode(event)

    async def _ensure_thread(self, body: RunAgentInput, prompt: str) -> _ThreadRef:
        """Resolve the thread this run belongs to, minting one if needed.

        An AG-UI client invents its own ``threadId``, and one that has never
        spoken to this server has invented an id that means nothing here.
        Keeping a mapping table would make the gateway stateful for no real
        gain, so the protocol's thread id is honoured as *this server's* thread
        id, and a run naming a thread we do not have creates one — announced
        back as a ``langalpha.thread`` event so a client that cares can adopt
        the real id. Refusing instead would make the first run of every
        conversation fail.
        """
        agent_mode, workspace_id = _options(body)
        if body.thread_id and await self._thread_exists(body.thread_id):
            # The messages path resolves the workspace from the thread row, so
            # an existing thread needs nothing passed for it.
            return _ThreadRef(body.thread_id, "", False)
        thread_id, resolved = await self.create_thread(prompt, agent_mode, workspace_id)
        return _ThreadRef(thread_id, resolved, True)

    async def _thread_exists(self, thread_id: str) -> bool:
        """Whether this caller owns a thread by that id.

        A transport failure raises rather than answering "no": answering "no"
        would silently mint a fresh thread and start the caller a new
        conversation the moment the probe blipped.
        """
        url = f"{_self_base_url()}/api/v1/threads/{thread_id}"
        try:
            resp = await self._http.get(
                url, headers=self._loopback_headers(), timeout=30.0
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"could not reach the thread index: {exc}") from exc
        return resp.status_code == 200

    async def create_thread(
        self, first_query: str, agent_mode: str = "ptc", workspace_id: str = ""
    ) -> tuple[str, str]:
        """Mint a thread, returning ``(thread_id, workspace_id)``.

        Public because a client that would rather name its conversation up
        front calls this before its first run instead of discovering the id
        mid-stream.
        """
        if agent_mode == "ptc" and not workspace_id:
            workspace_id = await self._resolve_workspace()
        payload: dict[str, Any] = {
            "first_query": first_query[:4000],
            "agent_mode": agent_mode,
        }
        if workspace_id:
            payload["workspace_id"] = workspace_id
        data = await self._json("POST", "/api/v1/threads", payload, timeout=120.0)
        thread_id = str((data or {}).get("thread_id") or "")
        if not thread_id:
            raise RuntimeError("thread creation returned no id")
        return thread_id, workspace_id

    async def _stream_turn(
        self, translator: Translator, ref: _ThreadRef, body: RunAgentInput, prompt: str
    ) -> AsyncIterator[dict[str, Any]]:
        """POST the turn and translate its frames as they arrive."""
        agent_mode, _ = _options(body)
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": prompt}],
            "agent_mode": agent_mode,
        }
        if ref.workspace_id:
            payload["workspace_id"] = ref.workspace_id

        url = f"{_self_base_url()}/api/v1/threads/{ref.thread_id}/messages"
        pending: list[str] = []
        async with self._http.stream(
            "POST", url, json=payload, headers=self._loopback_headers()
        ) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode("utf-8", "replace")
                for event in translator.abort(
                    f"turn rejected ({resp.status_code}): {detail[:300]}"
                ):
                    yield event
                return
            # Frames are parsed a block at a time: the event name lives on its
            # own line and has to be seen before the data line that uses it.
            async for line in resp.aiter_lines():
                if line.strip():
                    pending.append(line)
                    continue
                for event in translator.feed_lines(pending):
                    yield event
                pending.clear()
        # A stream whose last frame is not followed by a blank line still has
        # one frame left in hand.
        for event in translator.feed_lines(pending):
            yield event

    # ── workspace resolution ─────────────────────────────────────────────

    async def _resolve_workspace(self) -> str:
        """The caller's most recent workspace, or a new one.

        A ptc run needs a workspace and an external client has no way to name
        one. Most recent rather than first, because a run should continue the
        work the caller was last doing instead of starting a parallel context.
        Failing is deliberate: falling back to flash would silently answer a
        question the caller did not ask.
        """
        base, headers = _self_base_url(), self._loopback_headers()
        try:
            resp = await self._http.get(
                f"{base}/api/v1/workspaces",
                params={"limit": 1, "sort_by": "custom"},
                headers=headers,
                timeout=30.0,
            )
            resp.raise_for_status()
            rows = resp.json().get("workspaces") or []
            if rows:
                return str(rows[0]["workspace_id"])

            created = await self._http.post(
                f"{base}/api/v1/workspaces",
                json={"name": _WORKSPACE_NAME, "description": "AG-UI gateway"},
                headers=headers,
                timeout=300.0,
            )
            created.raise_for_status()
            return str(created.json().get("workspace_id") or "")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise RuntimeError(f"could not resolve a workspace: {exc}") from exc

    # ── small HTTP helper ────────────────────────────────────────────────

    async def _json(
        self, method: str, path: str, body: dict[str, Any], timeout: float = 60.0
    ) -> dict[str, Any] | None:
        try:
            resp = await self._http.request(
                method,
                f"{_self_base_url()}{path}",
                json=body,
                timeout=timeout,
                headers=self._loopback_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("agui loopback %s %s failed: %s", method, path, exc)
            return None
