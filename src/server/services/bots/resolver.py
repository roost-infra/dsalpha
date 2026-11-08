"""Which bot a turn belongs to, and what to do when the row does not say.

Every turn starts here, like ``turn_runtime`` for the workspace: the bot is
either the one the thread carries, or the default of the place the turn runs
(the workspace's analyst, or the user's Chief of Staff in Home). A legacy
thread that predates the bot layer gets stamped on first use, once, so the
next turn reads it without a write.

A paused bot does not answer: its threads stay readable but a send is refused
with a 409, and the same rule is what a room's dispatch checks before it
gives a slot to a member.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def resolve_turn_bot(
    user_id: str,
    *,
    thread_id: Optional[str] = None,
    thread_meta: Optional[Dict[str, Any]] = None,
    workspace: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """The bot this turn runs as, or None when the bot layer has nothing.

    ``thread_meta`` is the caller's read of the thread row (it may carry
    ``bot_id``); ``workspace`` the row the turn names, None for Home.
    Returning None is the legacy answer: a caller with no bot anywhere keeps
    the pre-bot role routing.
    """
    from src.server.database import bots as bot_db

    bot: Optional[Dict[str, Any]] = None
    carried = (thread_meta or {}).get("bot_id")
    if carried:
        bot = await bot_db.get_bot_for_user(user_id, carried)
        if bot is None:
            logger.warning(
                "[BOTS] thread %s carries bot %s, which this user no longer has; "
                "falling back to the place's default",
                thread_id,
                carried,
            )

    if bot is None:
        bot = await _default_bot(user_id, workspace)
        if bot is not None and thread_id and thread_meta is not None:
            # Legacy thread: stamp it once, so a bot's private chat is a
            # property of the thread from here on, not a guess each turn.
            try:
                await bot_db.bind_thread_bot(thread_id, bot["bot_id"])
            except Exception as exc:  # never fail a turn over a provenance write
                logger.warning(
                    "[BOTS] could not stamp thread %s with bot %s: %s",
                    thread_id,
                    bot.get("bot_id"),
                    exc,
                )

    if bot is None:
        return None

    # A bot belongs to one place; a thread found elsewhere (a moved thread, an
    # account merge) must not drag its old bot into the new place.
    if workspace is not None and str(bot["workspace_id"]) != str(
        workspace.get("workspace_id")
    ):
        logger.info(
            "[BOTS] bot %s belongs to workspace %s, not %s; using the place's default",
            bot.get("bot_id"),
            bot.get("workspace_id"),
            workspace.get("workspace_id"),
        )
        bot = await _default_bot(user_id, workspace)

    if bot is None:
        return None
    if bot.get("status") == "paused":
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "This bot"
                    f" ({bot.get('name') or bot.get('bot_id')}) is paused. "
                    "Resume it in Bots before sending a message."
                ),
                "type": "bot_paused",
                "bot_id": bot["bot_id"],
            },
        )
    return bot


async def _default_bot(
    user_id: str, workspace: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    from src.server.database import bots as bot_db

    if workspace is None:
        return await bot_db.ensure_home_bot(user_id)
    return await bot_db.ensure_workspace_bot(workspace)


def bot_role(bot: Optional[Dict[str, Any]]) -> Optional[str]:
    """The agent role a bot runs, or None to leave the routing to the place."""
    role = (bot or {}).get("role")
    return role if role in ("analyst", "chief_of_staff") else None
