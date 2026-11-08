"""Each room member answers in its own thread, created on first need.

The thread is the member's context boundary: the room log is injected into
it, never merged into it, so one member's history does not grow with another
member's. It is pinned in ``bot_threads`` under the room, which is also the
member's ``seen_seq`` cursor.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from src.server.database import bots as bot_db
from src.server.database import rooms as room_db

logger = logging.getLogger(__name__)


async def ensure_room_thread(room: Dict[str, Any], bot: Dict[str, Any]) -> str:
    thread_id = await room_db.get_room_thread(room["room_id"], bot["bot_id"])
    if thread_id:
        return thread_id
    from src.server.database.conversation.threads_write import ensure_thread_exists

    thread_id = str(uuid.uuid4())
    await ensure_thread_exists(
        workspace_id=str(bot["workspace_id"]),
        conversation_thread_id=thread_id,
        user_id=str(bot["user_id"]),
        initial_query="",
        initial_status="in_progress",
        resume=False,
    )
    await room_db.bind_room_thread(room["room_id"], bot["bot_id"], thread_id)
    await bot_db.bind_thread_bot(thread_id, bot["bot_id"], kind="room")
    logger.info(
        "[ROOM] minted thread %s for bot %s in room %s",
        thread_id,
        bot["bot_id"],
        room["room_id"],
    )
    return thread_id
