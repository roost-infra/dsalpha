"""Tools that let the agent push a message to the user's own WeChat bot.

Mirrors how athena does it: the agent gets a send tool rather than the platform
growing a delivery pipeline. That matters for scheduled work — an automation
whose prompt says "把结果发到微信" needs no webhook plumbing at all, because
the turn that produces the result is the turn that can send it.

The recipient is optional and falls back to the peer that last talked to this
user's bot, which is the user themselves in the ordinary case. Requiring an
explicit peer id would mean the model had to know one, which it does not.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.gateway.wechat import get_manager

logger = logging.getLogger(__name__)

__all__ = [
    "send_wechat_message",
    "list_wechat_contacts",
    "wechat_channel_status",
    "wechat_tools",
]


def _user_id(config: RunnableConfig) -> str:
    user_id = ((config or {}).get("configurable") or {}).get("user_id")
    if not user_id:
        raise ValueError("user_id not found in config")
    return str(user_id)


def _channel(config: RunnableConfig):
    """This user's channel, or None when they have not bound a bot."""
    manager = get_manager()
    if manager is None:
        return None
    return manager.get(_user_id(config))


def _default_recipient(binding: Any) -> str:
    """Who an unspecified send goes to: the configured target, else the peer
    who spoke last. Explicit config wins because an operator may want pushes to
    land somewhere other than wherever the last stray message came from."""
    configured = os.environ.get("WECHAT_DEFAULT_TO", "").strip()
    if configured:
        return configured
    peers = list(binding.peers.values()) if binding else []
    if not peers:
        return ""
    # A peer predating the recency field carries 0; sorting still picks one,
    # which is what a single-contact bot wants.
    return max(peers, key=lambda p: p.last_message_at or 0).peer


@tool
async def send_wechat_message(
    text: str, config: RunnableConfig, to: str = ""
) -> str:
    """Send a WeChat message to the user from their own bot — how a result
    reaches their phone, including from a scheduled automation.

    Use it when the user asks to be told / notified / 推送 something, and when a
    scheduled task's prompt says to send its output to WeChat. Send the finished
    answer, not a status update: it arrives on a phone with no other context.

    Args:
        text: The message body. Plain text or lightweight markdown; long
            reports are truncated by the platform, so lead with the conclusion.
        to: WeChat recipient id, only needed to reach a *different* contact
            than the last one who messaged this bot. Call
            list_wechat_contacts when unsure.

    Returns:
        Confirmation with the recipient and length — message delivery itself is
        fire-and-forget, so there is no reply to wait for.
    """
    binding = getattr(_channel(config), "binding", None)
    if binding is None:
        return (
            "微信通道不可用：当前账户还没有绑定微信机器人，"
            "需要先在 设置 → 微信 里扫码绑定。"
        )

    text = (text or "").strip()
    if not text:
        return "发送失败：text 不能为空。"

    recipient = (to or "").strip() or _default_recipient(binding)
    if not recipient:
        return (
            "发送失败：没有可用的收件人 —— 还没有人给这个机器人发过消息，"
            "也没有配置 WECHAT_DEFAULT_TO。请显式传 to。"
        )

    try:
        channel = _channel(config)
        await channel.send(recipient, text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("wechat send tool failed")
        return f"发送失败：{exc}"
    return f"已发送到 {recipient}（{len(text)} 字）。"


@tool
async def list_wechat_contacts(config: RunnableConfig) -> str:
    """List the WeChat contacts this bot has talked to, for picking a `to`.

    Returns:
        One line per contact with its id and when it last spoke — the id is what
        send_wechat_message takes.
    """
    manager = get_manager()
    binding = manager.binding(_user_id(config)) if manager is not None else None
    if binding is None or not binding.bound:
        return "微信未绑定：请先在 设置 → 微信 里扫码绑定。"
    if not binding.peers:
        return "还没有联系人跟这个机器人说过话，暂时没有可选的收件人。"
    lines = ["微信联系人："]
    for p in sorted(binding.peers.values(), key=lambda x: -(x.last_message_at or 0)):
        lines.append(f"- {p.peer}  （{p.messages} 条消息）")
    lines.append("把其中的 id 传给 send_wechat_message 的 to 参数即可。")
    return "\n".join(lines)


@tool
async def wechat_channel_status(config: RunnableConfig) -> str:
    """Check whether this account's WeChat bot is bound and connected.

    Use before promising to send something to WeChat — an unbound channel is
    silent about it until a send fails.

    Returns:
        Bound state, bot account, and agent mode.
    """
    manager = get_manager()
    if manager is None:
        return "微信通道未启用（服务端未设置 WECHAT_ENABLED）。"
    return str(manager.status(_user_id(config)))


def wechat_tools() -> list[Any]:
    """The WeChat push tools, for the agent's tool list."""
    return [send_wechat_message, list_wechat_contacts, wechat_channel_status]
