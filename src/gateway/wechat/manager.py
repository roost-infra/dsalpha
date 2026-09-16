"""Owns one WeChat channel per bound user.

Per-user binding means the channel is no longer a singleton: the set of running
poll loops is whatever users have scanned a QR. So the lifecycle questions that
were trivial with one channel — who starts it, what workspace it speaks into,
what happens when a user unbinds — all live here.

Workspace resolution happens at bind time and is stored on the binding. Doing
it once (rather than per message) keeps the hot path free of a lookup, and it
means a user who later renames or reorders their workspaces does not silently
move their phone's context somewhere else.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from src.gateway.wechat.channel import WeChatChannel, _self_base_url
from src.gateway.wechat.state import Binding, BindingStore, PeerThread

logger = logging.getLogger(__name__)

__all__ = ["WeChatManager"]

_WORKSPACE_NAME = os.environ.get("WECHAT_WORKSPACE_NAME", "微信")


class WeChatManager:
    """The set of running channels, keyed by user id."""

    def __init__(self, store: BindingStore | None = None) -> None:
        self.store = store or BindingStore()
        self._channels: dict[str, WeChatChannel] = {}
        self._http: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    # ── loopback identity (same contract as the channel's) ───────────────

    def _headers(self, user_id: str) -> dict[str, str]:
        token = os.environ.get("INTERNAL_SERVICE_TOKEN", "").strip()
        if not token or not user_id:
            return {}
        return {"X-Service-Token": token, "X-User-Id": user_id}

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Resume every binding on disk. One channel per bound user."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0))
        self._import_legacy()
        for user_id, binding in self.store.all().items():
            await self._start_channel(binding)
        if self._channels:
            logger.info("wechat manager resumed %d binding(s)", len(self._channels))

    def _import_legacy(self) -> None:
        """Adopt the pre-per-user single binding as this deployment's own.

        The old layout was one ``state.json`` holding one bot, implicitly the
        operator's. Per-user storage would not find it, which would silently
        stop a bot that is currently working — so it is imported for the
        configured owner (and the file renamed, so this runs once).
        """
        import json

        legacy = os.environ.get("WECHAT_STATE_PATH", "").strip()
        if not legacy:
            return
        path = Path(legacy).expanduser()
        owner = (
            os.environ.get("WECHAT_OWNER_USER_ID", "").strip()
            or os.environ.get("AUTH_USER_ID", "").strip()
        )
        if not path.is_file() or not owner or self.store.load(owner) is not None:
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("wechat legacy binding unreadable (%s); skipping import", exc)
            return
        if not raw.get("account_id") or not raw.get("token"):
            return

        binding = Binding(
            user_id=owner,
            account_id=raw.get("account_id", ""),
            token=raw.get("token", ""),
            base_url=raw.get("base_url", ""),
            workspace_id=os.environ.get("WECHAT_WORKSPACE_ID", "").strip(),
            agent_mode=os.environ.get("WECHAT_AGENT_MODE", "").strip(),
        )
        for peer, entry in (raw.get("peers") or {}).items():
            binding.peers[peer] = PeerThread(**entry)
        binding.recent = list(raw.get("recent", []))
        self.store.save(binding)
        path.rename(path.with_suffix(path.suffix + ".imported"))
        logger.info("wechat imported the legacy binding for %s", owner)

    async def shutdown(self) -> None:
        async with self._lock:
            channels, self._channels = list(self._channels.values()), {}
        for channel in channels:
            await channel.stop()
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _start_channel(self, binding: Binding) -> WeChatChannel:
        channel = WeChatChannel(binding, self.store)
        await channel.start()
        self._channels[binding.user_id] = channel
        return channel

    # ── binding ──────────────────────────────────────────────────────────

    async def bind(
        self, user_id: str, account_id: str, token: str, base_url: str = ""
    ) -> Binding:
        """Attach a freshly scanned bot to ``user_id`` and start its loop."""
        async with self._lock:
            binding = self.store.load(user_id) or Binding(user_id=user_id)
            binding.account_id, binding.token, binding.base_url = account_id, token, base_url
            if not binding.workspace_id:
                binding.workspace_id = await self._resolve_workspace(user_id)
            if not binding.agent_mode:
                binding.agent_mode = "ptc" if binding.workspace_id else "flash"
            self.store.save(binding)

            previous = self._channels.pop(user_id, None)
            if previous is not None:
                await previous.stop()

        channel = await self._start_channel(binding)
        logger.info(
            "wechat bound user=%s account=%s workspace=%s",
            user_id,
            account_id,
            binding.workspace_id or "-",
        )
        await channel.refresh_creds()
        return binding

    async def unbind(self, user_id: str) -> None:
        async with self._lock:
            channel = self._channels.pop(user_id, None)
        if channel is not None:
            await channel.stop()
        self.store.delete(user_id)
        logger.info("wechat unbound user=%s", user_id)

    # ── lookup ───────────────────────────────────────────────────────────

    def get(self, user_id: str) -> WeChatChannel | None:
        return self._channels.get(user_id)

    def binding(self, user_id: str) -> Binding | None:
        return self.store.load(user_id)

    def status(self, user_id: str) -> dict[str, Any]:
        channel = self._channels.get(user_id)
        if channel is None:
            binding = self.store.load(user_id)
            return {
                "bound": bool(binding and binding.bound),
                "account_id": binding.account_id if binding else "",
                "running": False,
                "peers": len(binding.peers) if binding else 0,
            }
        return channel.status()

    # ── workspace resolution ─────────────────────────────────────────────

    async def _resolve_workspace(self, user_id: str) -> str:
        """Pick the workspace this user's WeChat turns belong in.

        Their most recent workspace if they have one — a phone conversation
        should continue the work they were last doing, not start a parallel
        context. A user with none gets one created, because a channel with no
        workspace can only run in flash mode.
        """
        if self._http is None:
            return ""
        headers = self._headers(user_id)
        try:
            resp = await self._http.get(
                f"{_self_base_url()}/api/v1/workspaces",
                params={"limit": 1, "sort_by": "custom"},
                headers=headers,
                timeout=30.0,
            )
            resp.raise_for_status()
            rows = resp.json().get("workspaces") or []
            if rows:
                return str(rows[0]["workspace_id"])

            created = await self._http.post(
                f"{_self_base_url()}/api/v1/workspaces",
                json={"name": _WORKSPACE_NAME, "description": "微信通道"},
                headers=headers,
                timeout=300.0,
            )
            created.raise_for_status()
            return str(created.json().get("workspace_id") or "")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            # Binding still succeeds; the channel falls back to flash mode,
            # which is better than refusing the scan.
            logger.warning("wechat could not resolve a workspace for %s: %s", user_id, exc)
            return ""
