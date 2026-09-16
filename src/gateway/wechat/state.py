"""Durable state for the WeChat channel: bot credentials and peer→thread map.

A JSON file rather than a table because this is channel-local bookkeeping with
no relational questions asked of it, and because the QR bind must survive a
restart without a migration. Writes go through a temp file + rename so a crash
mid-write cannot leave a half-written binding that reads as a corrupt token.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["WeChatState", "PeerThread", "state_path"]

# How many inbound messages the /recent endpoint can show. Bounded because it
# is a debugging surface, not a message store — the thread holds the real history.
RECENT_LIMIT = 50


def state_path() -> Path:
    """Where the channel persists itself.

    ``WECHAT_STATE_PATH`` wins so a deployment can point it at a mounted
    volume; the default sits under the app's data dir, which is what a
    container without extra config gets.
    """
    explicit = os.environ.get("WECHAT_STATE_PATH")
    if explicit:
        return Path(explicit).expanduser()
    data_dir = os.environ.get("LANGALPHA_DATA_DIR", "/app/data")
    return Path(data_dir) / "wechat" / "state.json"


@dataclass
class PeerThread:
    """One WeChat peer and the thread their conversation lives in."""

    peer: str
    thread_id: str
    display_name: str = ""
    last_message_at: float = 0.0
    messages: int = 0


@dataclass
class WeChatState:
    """The whole channel state, loadable and saveable as one document."""

    account_id: str = ""
    token: str = ""
    base_url: str = ""
    # Drives the /recent debug view; the thread is the real record.
    recent: list[dict[str, Any]] = field(default_factory=list)
    peers: dict[str, PeerThread] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()
        self._path = state_path()
        self._loaded = False

    # ── persistence ──────────────────────────────────────────────────────

    async def load(self) -> "WeChatState":
        async with self._lock:
            self._load_locked()
        return self

    def _load_locked(self) -> None:
        self._loaded = True
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # A corrupt file loses the binding, not the server: the operator
            # re-binds by QR. Refusing to start would be the worse trade.
            logger.warning("wechat state file unreadable (%s); starting empty", exc)
            return
        self.account_id = raw.get("account_id", "")
        self.token = raw.get("token", "")
        self.base_url = raw.get("base_url", "")
        self.recent = list(raw.get("recent", []))[-RECENT_LIMIT:]
        self.peers = {
            p: PeerThread(**v) for p, v in (raw.get("peers") or {}).items()
        }

    async def save(self) -> None:
        async with self._lock:
            self._save_locked()

    def _save_locked(self) -> None:
        payload = {
            "account_id": self.account_id,
            "token": self.token,
            "base_url": self.base_url,
            "recent": self.recent[-RECENT_LIMIT:],
            "peers": {p: asdict(v) for p, v in self.peers.items()},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    # ── credential lifecycle ─────────────────────────────────────────────

    @property
    def bound(self) -> bool:
        return bool(self.account_id and self.token)

    def creds(self):
        """``Creds`` for the client, or None when unbound (the loop then parks)."""
        if not self.bound:
            return None
        from src.gateway.ilink.models import Creds

        return Creds(account_id=self.account_id, token=self.token, base_url=self.base_url)

    async def bind(self, account_id: str, token: str, base_url: str = "") -> None:
        self.account_id, self.token, self.base_url = account_id, token, base_url
        await self.save()

    async def unbind(self) -> None:
        self.account_id = self.token = self.base_url = ""
        await self.save()

    # ── peer bookkeeping ─────────────────────────────────────────────────

    def peer(self, peer: str) -> PeerThread | None:
        return self.peers.get(peer)

    async def note_inbound(self, peer: str, text: str, display_name: str = "") -> None:
        entry = self.peers.get(peer)
        if entry is not None:
            entry.messages += 1
            entry.last_message_at = time.time()
            if display_name:
                entry.display_name = display_name
        self.recent.append(
            {"peer": peer, "text": text[:500], "at": time.time(), "dir": "in"}
        )
        del self.recent[:-RECENT_LIMIT]
        await self.save()

    async def note_outbound(self, peer: str, text: str) -> None:
        self.recent.append(
            {"peer": peer, "text": text[:500], "at": time.time(), "dir": "out"}
        )
        del self.recent[:-RECENT_LIMIT]
        await self.save()

    async def remember_thread(
        self, peer: str, thread_id: str, display_name: str = ""
    ) -> None:
        entry = self.peers.get(peer) or PeerThread(peer=peer, thread_id=thread_id)
        entry.thread_id = thread_id
        if display_name:
            entry.display_name = display_name
        self.peers[peer] = entry
        await self.save()
