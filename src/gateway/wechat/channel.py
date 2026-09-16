"""The WeChat channel: inbound message → agent turn → reply, plus sending.

A turn runs by calling this app's own ``/api/v1/threads/...`` over loopback
rather than by re-entering the agent in-process. That is deliberate: the HTTP
path already owns thread persistence, the run ledger, sandbox provisioning,
MCP tool binding and SSE streaming, and a second entry point would have to
re-implement all of it and would drift. The cost is one localhost round trip
per message, which is not the expensive part of a turn.

Each WeChat peer gets one thread, so a conversation on the phone continues the
same context the web UI shows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx

from src.gateway.wechat.state import WeChatState

logger = logging.getLogger(__name__)

__all__ = ["WeChatChannel"]

# A research turn can legitimately run for minutes (sandbox + MCP tools).
_TURN_TIMEOUT_SEC = float(os.environ.get("WECHAT_TURN_TIMEOUT_SEC", "900"))
# iLink rejects oversized sends; keep replies well inside the limit.
_MAX_REPLY_CHARS = 1800


def _self_base_url() -> str:
    return os.environ.get("WECHAT_SELF_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


class WeChatChannel:
    """Owns the bot client, the poll loop, and the turn bridge."""

    def __init__(self, state: WeChatState) -> None:
        self.state = state
        self._client: Any = None
        self._task: asyncio.Task | None = None
        self._http: httpx.AsyncClient | None = None
        self.workspace_id = os.environ.get("WECHAT_WORKSPACE_ID", "").strip() or None
        mode = os.environ.get("WECHAT_AGENT_MODE", "").strip()
        self.agent_mode = mode or ("ptc" if self.workspace_id else "flash")

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the poll loop if a binding exists; otherwise stay idle.

        An unbound channel is the normal first-run state, so this logs and
        returns rather than raising — the QR bind endpoint flips it later
        without a restart (the loop re-reads credentials).
        """
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=_TURN_TIMEOUT_SEC))

        from src.gateway.ilink import ILinkClient

        creds = self.state.creds()
        self._client = ILinkClient(
            account_id=creds.account_id if creds else "",
            token=creds.token if creds else "",
            base_url=creds.base_url if creds else "",
        )
        self._task = self._client.start_poll(
            provider=self.state.creds,
            handler=self._handle,
            send_func=self._send_raw,
        )
        logger.info(
            "wechat channel started (bound=%s mode=%s workspace=%s)",
            self.state.bound,
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
            creds = self.state.creds()
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
        await self.state.note_outbound(to, text)

    # ── inbound ──────────────────────────────────────────────────────────

    async def _handle(self, from_: str, text: str) -> str | None:
        """One inbound message: run a turn, return the reply.

        Never raises: the poll loop treats a raised handler as a polling
        failure, and a single bad turn must not stop the channel receiving.
        """
        text = (text or "").strip()
        if not text:
            return None
        await self.state.note_inbound(from_, text)

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
        await self.state.note_outbound(from_, reply)
        return reply

    async def _ensure_thread(self, peer: str, first_query: str) -> str | None:
        entry = self.state.peer(peer)
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
        await self.state.remember_thread(peer, str(thread_id))
        return str(thread_id)

    async def _run_turn(self, thread_id: str, text: str) -> str:
        """POST the message and read the SSE stream down to the reply text."""
        if self._http is None:
            raise RuntimeError("wechat channel is not running")
        payload = {
            "messages": [{"role": "user", "content": text}],
            "agent_mode": self.agent_mode,
        }
        if self.workspace_id:
            payload["workspace_id"] = self.workspace_id

        url = f"{_self_base_url()}/api/v1/threads/{thread_id}/messages"
        chunks: list[str] = []
        error: str | None = None

        async with self._http.stream("POST", url, json=payload) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")
                raise RuntimeError(f"turn rejected ({resp.status_code}): {body[:300]}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("error"):
                    error = str(event["error"])
                    continue
                content = event.get("content")
                # reasoning_signal is the model's private channel; only the
                # answer text is a reply.
                if isinstance(content, str) and event.get("content_type") != "reasoning_signal":
                    chunks.append(content)

        if error:
            raise RuntimeError(error)
        return "".join(chunks).strip()

    # ── small HTTP helper ────────────────────────────────────────────────

    async def _json(
        self, method: str, path: str, body: dict[str, Any], timeout: float = 60.0
    ) -> dict[str, Any] | None:
        if self._http is None:
            return None
        try:
            resp = await self._http.request(
                method, f"{_self_base_url()}{path}", json=body, timeout=timeout
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("wechat loopback %s %s failed: %s", method, path, exc)
            return None

    def status(self) -> dict[str, Any]:
        return {
            "bound": self.state.bound,
            "account_id": self.state.account_id,
            "agent_mode": self.agent_mode,
            "workspace_id": self.workspace_id,
            "running": self._task is not None and not self._task.done(),
            "peers": len(self.state.peers),
        }
