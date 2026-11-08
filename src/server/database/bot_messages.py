"""Bot-to-bot messages: a persistent inbox, not a bus.

A message is delivered by injecting a user message into the target bot's
thread (the sender frame in the body is what tells the model who spoke). The
row is the durable truth: ``queued`` means accepted but not yet posted,
``delivered`` means a turn was admitted for it, ``consumed``/``failed`` are
terminal. ``idem`` makes a retried tool call the same message.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Json

from src.server.database.pool import get_db_connection
from src.server.utils.pg_sanitize import normalize_uuid

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 64 * 1024

MESSAGE_KINDS = ("message", "request", "reply", "report", "question", "notice")
STATUSES = ("queued", "delivered", "consumed", "failed")

_MESSAGE_COLUMNS = """
    message_id, user_id, from_type, from_id, to_bot_id, kind, content,
    payload, idem, status, thread_id, in_reply_to, root_id, attempts,
    last_attempt_at, created_at, delivered_at
"""


def _row_to_dict(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    out = dict(row)
    for key in ("message_id", "to_bot_id", "thread_id", "in_reply_to", "root_id"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    for key in ("created_at", "delivered_at"):
        value = out.get(key)
        if value is not None and hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


async def create_message(
    user_id: str,
    *,
    from_type: str,
    from_id: str,
    to_bot_id: Any,
    kind: str,
    content: str,
    payload: Optional[Dict[str, Any]] = None,
    idem: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    root_id: Optional[str] = None,
    conn=None,
) -> tuple[Dict[str, Any], bool]:
    """Persist one message. Returns ``(row, created)``.

    A repeated ``idem`` answers the existing row (``created=False``), which is
    what makes a retried tool call one message rather than two.
    """
    cleaned_target = normalize_uuid(str(to_bot_id)) if to_bot_id else None
    if cleaned_target is None:
        raise ValueError("to_bot_id is not a UUID")
    if kind not in MESSAGE_KINDS:
        raise ValueError(f"kind must be one of {MESSAGE_KINDS}")
    text = (content or "").strip()
    if not text:
        raise ValueError("content is empty")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValueError(f"content is longer than {MAX_MESSAGE_CHARS} bytes")
    async with get_db_connection(conn) as db:
        async with db.cursor(row_factory=dict_row) as cur:
            if idem:
                await cur.execute(
                    f"SELECT {_MESSAGE_COLUMNS} FROM bot_messages "
                    "WHERE user_id = %s AND idem = %s",
                    (user_id, idem),
                )
                existing = await cur.fetchone()
                if existing is not None:
                    return _row_to_dict(existing), False
            try:
                await cur.execute(
                    f"""
                    INSERT INTO bot_messages (
                        user_id, from_type, from_id, to_bot_id, kind, content,
                        payload, idem, in_reply_to, root_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING {_MESSAGE_COLUMNS}
                    """,
                    (
                        user_id,
                        from_type,
                        from_id,
                        cleaned_target,
                        kind,
                        text,
                        Json(payload or {}),
                        idem,
                        normalize_uuid(str(in_reply_to)) if in_reply_to else None,
                        normalize_uuid(str(root_id)) if root_id else None,
                    ),
                )
            except UniqueViolation:
                await cur.execute(
                    f"SELECT {_MESSAGE_COLUMNS} FROM bot_messages "
                    "WHERE user_id = %s AND idem = %s",
                    (user_id, idem),
                )
                return _row_to_dict(await cur.fetchone()), False
            return _row_to_dict(await cur.fetchone()), True


async def count_root_messages(root_id: Any) -> int:
    """How many messages this root chain already holds (the loop budget)."""
    cleaned = normalize_uuid(str(root_id)) if root_id else None
    if cleaned is None:
        return 0
    async with get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM bot_messages WHERE root_id = %s", (cleaned,)
            )
            return int((await cur.fetchone())[0])


async def count_recent_from(from_id: Any, *, seconds: int = 60) -> int:
    """Messages a bot sent in the last ``seconds`` (per-sender rate limit)."""
    from src.server.utils.pg_sanitize import normalize_uuid as _uuid

    cleaned = _uuid(str(from_id)) if from_id else None
    if cleaned is None:
        return 0
    async with get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM bot_messages "
                "WHERE from_type = 'bot' AND from_id = %s::uuid "
                "AND created_at > NOW() - make_interval(secs => %s)",
                (cleaned, int(seconds)),
            )
            return int((await cur.fetchone())[0])


async def set_message_root(message_id: Any, root_id: Any) -> None:
    """The first message of a chain is its own root, known only after insert."""
    cleaned_message = normalize_uuid(str(message_id)) if message_id else None
    cleaned_root = normalize_uuid(str(root_id)) if root_id else None
    if cleaned_message is None or cleaned_root is None:
        return
    async with get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE bot_messages SET root_id = %s "
                "WHERE message_id = %s AND root_id IS NULL",
                (cleaned_root, cleaned_message),
            )


async def get_message(message_id: Any) -> Optional[Dict[str, Any]]:
    cleaned = normalize_uuid(str(message_id)) if message_id else None
    if cleaned is None:
        return None
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_MESSAGE_COLUMNS} FROM bot_messages WHERE message_id = %s",
                (cleaned,),
            )
            return _row_to_dict(await cur.fetchone())


async def list_inbox(
    user_id: str, to_bot_id: Any, *, status: Optional[str] = None, limit: int = 20
) -> list[Dict[str, Any]]:
    cleaned = normalize_uuid(str(to_bot_id)) if to_bot_id else None
    if cleaned is None:
        return []
    where = ["user_id = %s", "to_bot_id = %s"]
    params: list[Any] = [user_id, cleaned]
    if status:
        where.append("status = %s")
        params.append(status)
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_MESSAGE_COLUMNS} FROM bot_messages "
                f"WHERE {' AND '.join(where)} ORDER BY created_at LIMIT %s",
                (*params, max(1, min(limit, 100))),
            )
            return [_row_to_dict(r) for r in await cur.fetchall()]


async def set_status(
    message_id: Any,
    status: str,
    *,
    thread_id: Optional[str] = None,
    conn=None,
) -> bool:
    """Move a message's status. ``delivered`` also stamps the thread posted to."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    cleaned = normalize_uuid(str(message_id)) if message_id else None
    if cleaned is None:
        return False
    async with get_db_connection(conn) as db:
        async with db.cursor() as cur:
            if status == "delivered":
                await cur.execute(
                    "UPDATE bot_messages SET status = %s, thread_id = %s, "
                    "delivered_at = NOW() WHERE message_id = %s",
                    (status, normalize_uuid(str(thread_id)) if thread_id else None, cleaned),
                )
            else:
                await cur.execute(
                    "UPDATE bot_messages SET status = %s WHERE message_id = %s",
                    (status, cleaned),
                )
            return cur.rowcount > 0


async def queued_for_thread(user_id: str, thread_id: Any) -> list[Dict[str, Any]]:
    """Queued messages waiting on one thread (the target bot's private one)."""
    cleaned = normalize_uuid(str(thread_id)) if thread_id else None
    if cleaned is None:
        return []
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_MESSAGE_COLUMNS} FROM bot_messages "
                "WHERE user_id = %s AND thread_id = %s AND status = 'queued' "
                "ORDER BY created_at",
                (user_id, cleaned),
            )
            return [_row_to_dict(r) for r in await cur.fetchall()]
