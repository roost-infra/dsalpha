"""The guest DM tools are bound on the main agent's tool surface."""

from __future__ import annotations

from src.tools.bots.tool import BOT_TOOLS


def test_guest_dm_tools_are_registered() -> None:
    names = {tool.name for tool in BOT_TOOLS}
    assert "send_invite_message" in names
    assert "reply_guest_message" in names
