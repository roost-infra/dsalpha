"""A room member's tools: read the shared log, post into it.

A member answers inside a round without these; they are for what a round does
not cover — checking what was said while it was elsewhere, or leaving a note
the next round's increments will carry.
"""

from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.tools.secretary._commands import InjectedToolCallId

from src.server.database import rooms as room_db
from src.server.services.rooms.context import sender_label

logger = logging.getLogger(__name__)

_READ_LIMIT = 30


def _context(config: RunnableConfig) -> tuple[str, str, str]:
    conf = (config or {}).get("configurable") or {}
    user_id = conf.get("user_id")
    thread_id = conf.get("thread_id")
    if not user_id or not thread_id:
        raise ValueError("this turn has no user or thread identity")
    return str(user_id), str(thread_id), str(conf.get("workspace_id") or "")


async def _my_room(thread_id: str) -> tuple[str, str]:
    room_id = await room_db.room_for_thread(thread_id)
    if room_id is None:
        raise ValueError("this thread is not a room member")
    from src.server.database import bots as bot_db

    bot_id = await bot_db.get_thread_bot_id(thread_id)
    if bot_id is None:
        raise ValueError("this thread has no bot identity")
    return room_id, bot_id


@tool("read_room")
async def read_room(config: RunnableConfig) -> str:
    """Read the recent messages of the room this thread belongs to.

    Use it when you need what was said while you were busy elsewhere; a round
    already hands you the increments, so this is for the gap between rounds.

    Returns:
        The last 30 entries, oldest first, one per line with sender and seq.
    """
    _user_id, thread_id, _workspace_id = _context(config)
    try:
        room_id, _bot_id = await _my_room(thread_id)
    except ValueError as exc:
        return f"refused: {exc}"
    room = await room_db.get_room(room_id)
    members = await room_db.list_members_with_bots(room_id)
    entries = await room_db.read_log(room_id, since_seq=0, limit=_READ_LIMIT)
    header = f'[Room "{room.get("name") if room else room_id}"]'
    if not entries:
        return f"{header}\nNo messages yet."
    lines = [header]
    for entry in entries:
        label = sender_label(entry, members)
        lines.append(f"[{entry['seq']}] {label}: {entry['content']}")
    return "\n".join(lines)


@tool("post_to_room")
async def post_to_room(
    content: str,
    config: RunnableConfig,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> str:
    """Post one message into the room this thread belongs to.

    The message joins the shared log and is read by the next round's members.
    Use it for a note that should be on the record, not for answering a round
    — a round's reply is written for you.

    Returns:
        The seq the message landed at, or a refusal when this thread is not a
        room member.
    """
    _user_id, thread_id, _workspace_id = _context(config)
    try:
        room_id, bot_id = await _my_room(thread_id)
    except ValueError as exc:
        return f"refused: {exc}"
    text = (content or "").strip()
    if not text:
        return "refused: the message is empty"
    if len(text) > 64 * 1024:
        return "refused: the message is over 64 KB; keep room messages short"
    entry = await room_db.append_log(
        room_id,
        sender_type="bot",
        sender_id=bot_id,
        content=text,
    )
    return f"posted at seq {entry['seq']}"


@tool("read_own_chat")
async def read_own_chat(config: RunnableConfig, turns: int = 3) -> str:
    """Read the last turns of your own private chat with the user.

    Use it when the room needs what you already worked out with the user; the
    room records that you looked, so a claim in the room is traceable to it.

    Args:
        turns: How many of your most recent turns to read (default 3).

    Returns:
        The turns, oldest first, with their run labels; empty when you have no
        private turns yet.
    """
    _user_id, thread_id, _workspace_id = _context(config)
    from src.server.database import bots as bot_db

    bot_id = await bot_db.get_thread_bot_id(thread_id)
    if bot_id is None:
        return "refused: this thread has no bot identity"
    private_thread = await bot_db.get_bot_thread_thread_id(bot_id, kind="private")
    if not private_thread:
        return "No private chat yet."
    from src.tools.secretary.utils import extract_text_from_thread

    conf = (config or {}).get("configurable") or {}
    result = await extract_text_from_thread(
        private_thread, max(1, min(int(turns), 10)), timezone=conf.get("timezone") or "UTC"
    )
    text = (result or {}).get("text") or ""
    room_id = await room_db.room_for_thread(thread_id)
    if room_id:
        bot = await bot_db.get_bot(bot_id)
        await room_db.append_log(
            room_id,
            sender_type="system",
            sender_id="room",
            kind="status",
            content=f"{(bot or {}).get('name') or 'A member'} consulted its own chat.",
        )
    return text.strip() or "No private turns yet."


ROOM_TOOLS = [read_room, post_to_room, read_own_chat]
