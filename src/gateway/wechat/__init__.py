"""WeChat channel: bind a bot by QR and talk to the agent from WeChat.

The channel is off until ``WECHAT_ENABLED`` is set (or a binding already
exists), so importing this package never opens a socket. ``init_channel`` is
what the app lifespan calls; ``get_channel`` is what the router reads.
"""

from __future__ import annotations

import logging
import os

from src.gateway.wechat.channel import WeChatChannel
from src.gateway.wechat.state import WeChatState, state_path

logger = logging.getLogger(__name__)

__all__ = [
    "WeChatChannel",
    "WeChatState",
    "state_path",
    "init_channel",
    "get_channel",
    "shutdown_channel",
]

_channel: WeChatChannel | None = None


def enabled() -> bool:
    """Whether to run the channel at all.

    An already-bound bot implies on: an operator who scanned a QR expects it to
    keep working after a restart without also setting a flag.
    """
    flag = os.environ.get("WECHAT_ENABLED", "").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    return state_path().is_file()


async def init_channel() -> WeChatChannel | None:
    """Load state and start polling. Returns None when the channel is off."""
    global _channel
    if not enabled():
        logger.info("wechat channel disabled (set WECHAT_ENABLED=1 to run it)")
        return None
    if _channel is not None:
        return _channel
    state = await WeChatState().load()
    _channel = WeChatChannel(state)
    try:
        await _channel.start()
    except Exception as exc:  # noqa: BLE001
        # A channel that cannot start must not take the API down with it.
        logger.exception("wechat channel failed to start: %s", exc)
        _channel = None
    return _channel


def get_channel() -> WeChatChannel | None:
    return _channel


async def shutdown_channel() -> None:
    global _channel
    if _channel is not None:
        await _channel.stop()
        _channel = None
