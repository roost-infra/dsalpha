"""WeChat channel: each user binds their own bot and talks to the agent from it.

The manager is off until ``WECHAT_ENABLED`` is set (or at least one binding
exists on disk), so importing this package never opens a socket. ``init_channel``
is what the app lifespan calls; ``get_manager`` is what the router reads.
"""

from __future__ import annotations

import logging
import os

from src.gateway.wechat.channel import WeChatChannel
from src.gateway.wechat.manager import WeChatManager
from src.gateway.wechat.state import Binding, BindingStore, store_root

logger = logging.getLogger(__name__)

__all__ = [
    "Binding",
    "BindingStore",
    "WeChatChannel",
    "WeChatManager",
    "store_root",
    "init_channel",
    "get_manager",
    "shutdown_channel",
]

_manager: WeChatManager | None = None


def enabled() -> bool:
    """Whether to run the channel at all.

    An existing binding implies on: a user who scanned a QR expects their bot to
    keep working after a restart without anyone also setting a flag.
    """
    flag = os.environ.get("WECHAT_ENABLED", "").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    return bool(BindingStore().all())


async def init_channel() -> WeChatManager | None:
    """Start a channel per binding. Returns None when the channel is off."""
    global _manager
    if not enabled():
        logger.info("wechat channel disabled (set WECHAT_ENABLED=1 to run it)")
        return None
    if _manager is not None:
        return _manager
    manager = WeChatManager()
    try:
        await manager.start()
    except Exception as exc:  # noqa: BLE001
        # A channel that cannot start must not take the API down with it.
        logger.exception("wechat manager failed to start: %s", exc)
        return None
    _manager = manager
    return _manager


def get_manager() -> WeChatManager | None:
    return _manager


async def shutdown_channel() -> None:
    global _manager
    if _manager is not None:
        await _manager.shutdown()
        _manager = None
