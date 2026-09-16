"""Per-user WeChat bindings.

One bot per user: each user scans their own QR, and their inbound messages run
turns as *them*, in their own workspace. So the durable unit is a binding keyed
by the app user, not a single global document.

Storage is one JSON file per user under a directory. A directory rather than a
single keyed document because writes are per-user and a corrupt file should
cost one user their binding, not everyone's — and because the set of users
grows without anyone having to load and rewrite the whole thing.

``user_id`` reaches the filesystem, so it is validated rather than trusted:
even though it arrives from a verified JWT, a path-shaped id must never reach
outside the directory.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["Binding", "BindingStore", "PeerThread", "store_root"]

# App user ids are UUIDs (Supabase) or the oss local user; anything else is not
# something we will name a file after.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")

RECENT_LIMIT = 50


def store_root() -> Path:
    """Directory holding one binding file per user."""
    explicit = os.environ.get("WECHAT_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    # The pre-per-user deployment wrote a single state.json; keep its parent so
    # an upgrade lands beside it rather than somewhere unrelated.
    legacy = os.environ.get("WECHAT_STATE_PATH")
    if legacy:
        return Path(legacy).expanduser().parent / "bindings"
    return Path(os.environ.get("LANGALPHA_DATA_DIR", "/app/data")) / "wechat" / "bindings"


@dataclass
class PeerThread:
    """One WeChat peer and the thread their conversation lives in."""

    peer: str
    thread_id: str
    display_name: str = ""
    last_message_at: float = 0.0
    messages: int = 0


@dataclass
class Binding:
    """One user's bot: credentials, their peers, and a short message log."""

    user_id: str
    account_id: str = ""
    token: str = ""
    base_url: str = ""
    # The workspace this user's WeChat turns land in. Resolved when they bind,
    # so each user's phone continues *their* work rather than a shared one.
    workspace_id: str = ""
    agent_mode: str = ""
    peers: dict[str, PeerThread] = field(default_factory=dict)
    recent: list[dict[str, Any]] = field(default_factory=list)

    @property
    def mode(self) -> str:
        return self.agent_mode or ("ptc" if self.workspace_id else "flash")

    @property
    def bound(self) -> bool:
        return bool(self.account_id and self.token)

    def creds(self):
        """``Creds`` for the client, or None when unbound."""
        if not self.bound:
            return None
        from src.gateway.ilink.models import Creds

        return Creds(
            account_id=self.account_id, token=self.token, base_url=self.base_url
        )

    def peer(self, peer: str) -> PeerThread | None:
        return self.peers.get(peer)

    def note(self, direction: str, peer: str, text: str) -> None:
        self.recent.append(
            {"peer": peer, "text": text[:500], "at": time.time(), "dir": direction}
        )
        del self.recent[:-RECENT_LIMIT]
        # Keep the peer row current too. Without this the row's timestamp stays
        # at its creation value, and anything that ranks peers by recency —
        # notably the default recipient for an agent-initiated push — picks the
        # wrong one (or, for a peer created before the first note, none at all).
        entry = self.peers.get(peer)
        if entry is not None:
            entry.last_message_at = time.time()
            if direction == "in":
                entry.messages += 1

    def remember_thread(self, peer: str, thread_id: str, display_name: str = "") -> None:
        entry = self.peers.get(peer) or PeerThread(peer=peer, thread_id=thread_id)
        entry.thread_id = thread_id
        if display_name:
            entry.display_name = display_name
        self.peers[peer] = entry


class BindingStore:
    """Directory of per-user bindings, with atomic writes."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or store_root()

    # ── paths ────────────────────────────────────────────────────────────

    def _path(self, user_id: str) -> Path:
        if not _USER_ID_RE.match(user_id or ""):
            raise ValueError(f"unsafe user id for a binding file: {user_id!r}")
        return self.root / f"{user_id}.json"

    # ── reads ────────────────────────────────────────────────────────────

    def load(self, user_id: str) -> Binding | None:
        try:
            path = self._path(user_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # A corrupt file loses that user's binding (they re-scan); refusing
            # to start the channel would be the worse trade.
            logger.warning("wechat binding unreadable for %s (%s)", user_id, exc)
            return None
        peers = {p: PeerThread(**v) for p, v in (raw.get("peers") or {}).items()}
        return Binding(
            user_id=user_id,
            account_id=raw.get("account_id", ""),
            token=raw.get("token", ""),
            base_url=raw.get("base_url", ""),
            workspace_id=raw.get("workspace_id", ""),
            agent_mode=raw.get("agent_mode", ""),
            peers=peers,
            recent=list(raw.get("recent", []))[-RECENT_LIMIT:],
        )

    def all(self) -> dict[str, Binding]:
        """Every binding on disk, keyed by user. Unreadable files are skipped."""
        out: dict[str, Binding] = {}
        if not self.root.is_dir():
            return out
        for path in sorted(self.root.glob("*.json")):
            binding = self.load(path.stem)
            if binding is not None:
                out[binding.user_id] = binding
        return out

    # ── writes ───────────────────────────────────────────────────────────

    def save(self, binding: Binding) -> None:
        path = self._path(binding.user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "account_id": binding.account_id,
            "token": binding.token,
            "base_url": binding.base_url,
            "workspace_id": binding.workspace_id,
            "agent_mode": binding.agent_mode,
            "recent": binding.recent[-RECENT_LIMIT:],
            "peers": {p: asdict(v) for p, v in binding.peers.items()},
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, path)

    def delete(self, user_id: str) -> None:
        try:
            self._path(user_id).unlink(missing_ok=True)
        except ValueError:
            return
