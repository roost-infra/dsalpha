"""One user's WeChat channel: inbound message → agent turn → reply, plus sending.

A turn runs by calling this app's own ``/api/v1/threads/...`` over loopback
rather than by re-entering the agent in-process. That is deliberate: the HTTP
path already owns thread persistence, the run ledger, sandbox provisioning,
MCP tool binding and SSE streaming, and a second entry point would have to
re-implement all of it and would drift. The cost is one localhost round trip
per message, which is not the expensive part of a turn.

Each WeChat peer gets one thread, so a conversation on the phone continues the
same context the web UI shows. Each *user* gets their own channel, bot and
workspace — ``WeChatManager`` owns the set of them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Iterable
from typing import Any

import httpx

from src.gateway.wechat.state import Binding, BindingStore

logger = logging.getLogger(__name__)

__all__ = ["WeChatChannel", "extract_reply"]

# A research turn can legitimately run for minutes (sandbox + MCP tools).
_TURN_TIMEOUT_SEC = float(os.environ.get("WECHAT_TURN_TIMEOUT_SEC", "900"))
# iLink rejects oversized sends; keep replies well inside the limit.
_MAX_REPLY_CHARS = 1800


def _self_base_url() -> str:
    return os.environ.get("WECHAT_SELF_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def extract_reply(lines: Iterable[str]) -> tuple[str, str | None]:
    """Reduce an SSE turn stream to (reply, error).

    The stream carries far more than the answer, and taking the wrong slice
    sends the wrong thing to a phone. Three separate traps, all of which were
    hit before this was a function:

    - reasoning arrives both as its own ``event: reasoning_content`` and as
      ``message_chunk`` with ``content_type: 'reasoning'``;
    - the ``tools`` agent reports tool *results* under ``content_type: 'text'``;
    - the model narrates ("let me search the vault") before calling a tool.

    So: only ``event: message_chunk`` with ``content_type: 'text'`` from a
    ``model:`` agent, and the buffer is reset at every tool call — the reply is
    what comes after the last tool result.

    Pure over lines so the rule can be pinned against recorded streams.
    """
    chunks: list[str] = []
    error: str | None = None
    event_name = ""

    for line in lines:
        # The event name is its own SSE line and has no counterpart in the JSON
        # payload, so dropping it loses reasoning_content entirely.
        if line.startswith("event: "):
            event_name = line[7:].strip()
            continue
        if not line.startswith("data: "):
            continue
        try:
            frame = json.loads(line[6:])
        except ValueError:
            continue
        if not isinstance(frame, dict):
            continue
        if frame.get("error"):
            error = str(frame["error"])
            continue
        if event_name in ("tool_calls", "tool_call_chunks", "tool_call_result"):
            chunks.clear()
            continue
        if event_name != "message_chunk":
            continue
        if not str(frame.get("agent") or "").startswith("model:"):
            continue
        if frame.get("tool_call_id"):
            continue
        if frame.get("content_type") != "text":
            continue
        content = frame.get("content")
        if isinstance(content, str):
            chunks.append(content)

    return "".join(chunks).strip(), error


class WeChatChannel:
    """Owns one user's bot client, its poll loop, and the turn bridge."""

    def __init__(self, binding: Binding, store: BindingStore) -> None:
        self.binding = binding
        self.store = store
        self._client: Any = None
        self._task: asyncio.Task | None = None
        self._http: httpx.AsyncClient | None = None

    # ── identity ─────────────────────────────────────────────────────────

    @property
    def user_id(self) -> str:
        return self.binding.user_id

    @property
    def workspace_id(self) -> str | None:
        return self.binding.workspace_id or None

    @property
    def agent_mode(self) -> str:
        return self.binding.mode

    def _loopback_headers(self) -> dict[str, str]:
        """Headers that identify this channel to the app's own API.

        In ``HOST_MODE=oss`` none are needed. In ``platform`` every endpoint
        resolves a caller from a Bearer JWT, which a server-side channel has no
        way to hold, so it authenticates as a service instead
        (``get_current_user_id`` accepts X-Service-Token + X-User-Id). The
        identity is the binding's own user, so the turn lands in *their*
        workspace. Without this the channel 401s the moment auth is switched on.
        """
        token = os.environ.get("INTERNAL_SERVICE_TOKEN", "").strip()
        if not token or not self.user_id:
            return {}
        return {"X-Service-Token": token, "X-User-Id": self.user_id}

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the poll loop if a binding exists; otherwise stay idle.

        An unbound channel is the normal first-run state, so this logs and
        returns rather than raising — the QR bind endpoint flips it later
        without a restart (the loop re-reads credentials).
        """
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=_TURN_TIMEOUT_SEC))

        from src.gateway.ilink import ILinkClient

        creds = self.binding.creds()
        self._client = ILinkClient(
            account_id=creds.account_id if creds else "",
            token=creds.token if creds else "",
            base_url=creds.base_url if creds else "",
        )
        self._task = self._client.start_poll(
            provider=self.binding.creds,
            handler=self._handle,
            send_func=self._send_raw,
        )
        logger.info(
            "wechat channel started for %s (bound=%s mode=%s workspace=%s)",
            self.user_id,
            self.binding.bound,
            self.agent_mode,
            self.workspace_id or "-",
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def refresh_creds(self) -> None:
        """Push a fresh binding into the running client (no restart needed)."""
        if self._client is not None:
            creds = self.binding.creds()
            if creds is not None:
                self._client.set_creds(creds.account_id, creds.token, creds.base_url)

    # ── sending ──────────────────────────────────────────────────────────

    async def _send_raw(self, to: str, text: str) -> None:
        if self._client is None:
            raise RuntimeError("wechat channel is not running")
        await self._client.send_text(to, text)

    async def send(self, to: str, text: str) -> None:
        """Send a message the server initiated (endpoint / automation)."""
        await self._send_raw(to, text)
        self.binding.note("out", to, text)
        self.store.save(self.binding)

    # ── inbound ──────────────────────────────────────────────────────────

    async def _handle(self, from_: str, text: str) -> str | None:
        """One inbound message: run a turn, return the reply.

        Never raises: the poll loop treats a raised handler as a polling
        failure, and a single bad turn must not stop the channel receiving.
        """
        text = (text or "").strip()
        if not text:
            return None
        self.binding.note("in", from_, text)
        self.store.save(self.binding)

        try:
            thread_id = await self._ensure_thread(from_, text)
            if thread_id is None:
                return "抱歉，服务端暂时无法创建会话，请稍后重试。"
            reply = await self._run_turn(thread_id, text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("wechat turn failed for %s: %s", from_, exc)
            return "抱歉，这次分析出错了，请稍后再试。"

        reply = (reply or "").strip()
        if not reply:
            return None
        if len(reply) > _MAX_REPLY_CHARS:
            reply = reply[: _MAX_REPLY_CHARS - 1].rstrip() + "…"
        self.binding.note("out", from_, reply)
        self.store.save(self.binding)
        return reply

    async def _ensure_thread(self, peer: str, first_query: str) -> str | None:
        entry = self.binding.peer(peer)
        if entry is not None and entry.thread_id:
            return entry.thread_id

        body: dict[str, Any] = {
            "first_query": first_query[:4000],
            "agent_mode": self.agent_mode,
        }
        if self.workspace_id:
            body["workspace_id"] = self.workspace_id
        data = await self._json("POST", "/api/v1/threads", body, timeout=120.0)
        if not data:
            return None
        thread_id = data.get("thread_id") or data.get("id")
        if not thread_id:
            logger.warning("thread create returned no id: %s", str(data)[:200])
            return None
        self.binding.remember_thread(peer, str(thread_id))
        self.store.save(self.binding)
        return str(thread_id)

    async def _run_turn(self, thread_id: str, text: str) -> str:
        """POST the message and stream the turn down to just the reply text."""
        if self._http is None:
            raise RuntimeError("wechat channel is not running")
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": text}],
            "agent_mode": self.agent_mode,
        }
        if self.workspace_id:
            payload["workspace_id"] = self.workspace_id

        url = f"{_self_base_url()}/api/v1/threads/{thread_id}/messages"
        async with self._http.stream(
            "POST", url, json=payload, headers=self._loopback_headers()
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")
                raise RuntimeError(f"turn rejected ({resp.status_code}): {body[:300]}")
            lines = [line async for line in resp.aiter_lines()]

        reply, error = extract_reply(lines)
        if error:
            raise RuntimeError(error)
        return reply

    # ── small HTTP helper ────────────────────────────────────────────────

    async def _json(
        self, method: str, path: str, body: dict[str, Any], timeout: float = 60.0
    ) -> dict[str, Any] | None:
        if self._http is None:
            return None
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
            logger.warning("wechat loopback %s %s failed: %s", method, path, exc)
            return None

    def status(self) -> dict[str, Any]:
        return {
            "bound": self.binding.bound,
            "account_id": self.binding.account_id,
            "agent_mode": self.agent_mode,
            "workspace_id": self.workspace_id,
            "running": self._task is not None and not self._task.done(),
            "peers": len(self.binding.peers),
        }
