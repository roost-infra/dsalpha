"""Guest bot DM persistence: invites, directional consent, and inbox scans.

The platform keeps every user's bots in one database, but a bot may reach a bot
of another account only through a link the receiving owner minted. This module
owns those two tables and the small scans the delivery path needs; the turn
semantics stay in ``services/guest_dm`` and in the existing bot-message
delivery path.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row

from src.server.database.pool import get_db_connection
from src.server.utils.pg_sanitize import normalize_uuid

logger = logging.getLogger(__name__)

#: Token prefix so a pasted link is recognizable and strippable.
TOKEN_PREFIX = "dm_"
TOKEN_BYTES = 32

_INVITE_COLUMNS = """
    invite_id, bot_id, owner_user_id, created_by, expires_at, max_uses, uses,
    status, created_at
"""
_CONTACT_COLUMNS = """
    owner_user_id, bot_id, peer_bot_id, peer_user_id, status, invite_id,
    created_at, updated_at
"""


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()


def _row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for key in ("invite_id", "bot_id", "peer_bot_id", "owner_user_id", "peer_user_id"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    for key in ("created_at", "updated_at", "expires_at"):
        value = out.get(key)
        if value is not None and hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


async def create_invite(
    owner_user_id: str,
    bot_id: Any,
    *,
    created_by: str,
    token_hash: str,
    expires_at: datetime | None = None,
    max_uses: int = 1,
) -> dict[str, Any]:
    cleaned = normalize_uuid(str(bot_id)) if bot_id else None
    if cleaned is None:
        raise ValueError("bot_id is not a UUID")
    async with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            INSERT INTO bot_dm_invites (
                bot_id, owner_user_id, token_hash, created_by, expires_at, max_uses
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {_INVITE_COLUMNS}
            """,
            (cleaned, owner_user_id, token_hash, created_by, expires_at, max(1, max_uses)),
        )
        return _row(await cur.fetchone())  # type: ignore[return-value]


async def list_invites(
    owner_user_id: str, bot_id: Any = None
) -> list[dict[str, Any]]:
    sql = f"SELECT {_INVITE_COLUMNS} FROM bot_dm_invites WHERE owner_user_id = %s"
    params: list[Any] = [owner_user_id]
    if bot_id:
        cleaned = normalize_uuid(str(bot_id))
        if cleaned is None:
            return []
        sql += " AND bot_id = %s"
        params.append(cleaned)
    sql += " ORDER BY created_at DESC"
    async with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, tuple(params))
        return [r for r in (_row(x) for x in await cur.fetchall()) if r]


async def revoke_invite(owner_user_id: str, invite_id: Any) -> bool:
    cleaned = normalize_uuid(str(invite_id)) if invite_id else None
    if cleaned is None:
        return False
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE bot_dm_invites SET status = 'revoked' "
            "WHERE invite_id = %s AND owner_user_id = %s AND status = 'active'",
            (cleaned, owner_user_id),
        )
        return cur.rowcount > 0


async def get_invite_by_hash(token_hash: str) -> dict[str, Any] | None:
    """The live invite a token names, joined with the receiving bot.

    An expired, revoked, exhausted or deleted-bot invite answers None: the
    caller treats all four as "this link no longer works" rather than leaking
    which one it was.
    """
    async with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            SELECT {", ".join("i." + c.strip() for c in _INVITE_COLUMNS.split(","))},
                   b.user_id AS bot_owner_user_id,
                   b.workspace_id AS bot_workspace_id,
                   b.name AS bot_name,
                   b.approval AS bot_approval,
                   b.status AS bot_status
            FROM bot_dm_invites i
            JOIN bots b ON b.bot_id = i.bot_id AND b.deleted_at IS NULL
            WHERE i.token_hash = %s
              AND i.status = 'active'
              AND i.uses < i.max_uses
              AND (i.expires_at IS NULL OR i.expires_at > NOW())
            """,
            (token_hash,),
        )
        return _row(await cur.fetchone())


async def claim_invite_use(invite_id: Any) -> bool:
    """Spend one use under a single UPDATE so two senders cannot both win."""
    cleaned = normalize_uuid(str(invite_id)) if invite_id else None
    if cleaned is None:
        return False
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE bot_dm_invites SET uses = uses + 1 "
            "WHERE invite_id = %s AND status = 'active' AND uses < max_uses "
            "AND (expires_at IS NULL OR expires_at > NOW())",
            (cleaned,),
        )
        return cur.rowcount > 0


async def get_contact(bot_id: Any, peer_bot_id: Any) -> dict[str, Any] | None:
    cleaned = normalize_uuid(str(bot_id)) if bot_id else None
    peer = normalize_uuid(str(peer_bot_id)) if peer_bot_id else None
    if cleaned is None or peer is None:
        return None
    async with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {_CONTACT_COLUMNS} FROM bot_dm_contacts "
            "WHERE bot_id = %s AND peer_bot_id = %s",
            (cleaned, peer),
        )
        return _row(await cur.fetchone())


async def list_contacts(owner_user_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    sql = (
        f"SELECT {_CONTACT_COLUMNS} FROM bot_dm_contacts WHERE owner_user_id = %s"
    )
    params: list[Any] = [owner_user_id]
    if status:
        sql += " AND status = %s"
        params.append(status)
    sql += " ORDER BY updated_at DESC"
    async with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, tuple(params))
        return [r for r in (_row(x) for x in await cur.fetchall()) if r]


async def create_pending(
    owner_user_id: str,
    bot_id: Any,
    peer_bot_id: Any,
    peer_user_id: str,
    invite_id: Any = None,
) -> dict[str, Any] | None:
    """Record the first contact attempt without disturbing an accepted pair."""
    cleaned = normalize_uuid(str(bot_id)) if bot_id else None
    peer = normalize_uuid(str(peer_bot_id)) if peer_bot_id else None
    if cleaned is None or peer is None:
        return None
    invite = normalize_uuid(str(invite_id)) if invite_id else None
    async with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            INSERT INTO bot_dm_contacts (
                owner_user_id, bot_id, peer_bot_id, peer_user_id, status, invite_id
            ) VALUES (%s, %s, %s, %s, 'pending', %s)
            ON CONFLICT (bot_id, peer_bot_id) DO UPDATE
            SET invite_id = COALESCE(EXCLUDED.invite_id, bot_dm_contacts.invite_id),
                updated_at = NOW()
            WHERE bot_dm_contacts.status = 'pending'
            RETURNING {_CONTACT_COLUMNS}
            """,
            (owner_user_id, cleaned, peer, peer_user_id, invite),
        )
        row = await cur.fetchone()
        if row is not None:
            return _row(row)
    return await get_contact(cleaned, peer)


async def accept_contact(
    owner_user_id: str, bot_id: Any, peer_bot_id: Any
) -> dict[str, Any] | None:
    """Accept a pending request and write the mirror row the reply needs."""
    cleaned = normalize_uuid(str(bot_id)) if bot_id else None
    peer = normalize_uuid(str(peer_bot_id)) if peer_bot_id else None
    if cleaned is None or peer is None:
        return None
    async with get_db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            UPDATE bot_dm_contacts
            SET status = 'accepted', updated_at = NOW()
            WHERE owner_user_id = %s AND bot_id = %s AND peer_bot_id = %s
              AND status IN ('pending', 'accepted')
            RETURNING {_CONTACT_COLUMNS}
            """,
            (owner_user_id, cleaned, peer),
        )
        accepted = await cur.fetchone()
        if accepted is None:
            return None
        await cur.execute(
            """
            INSERT INTO bot_dm_contacts (
                owner_user_id, bot_id, peer_bot_id, peer_user_id, status, invite_id
            ) VALUES (%s, %s, %s, %s, 'accepted', %s)
            ON CONFLICT (bot_id, peer_bot_id) DO UPDATE
            SET status = 'accepted', updated_at = NOW()
            WHERE bot_dm_contacts.status IN ('pending', 'accepted')
            """,
            (
                str(accepted["peer_user_id"]),
                peer,
                cleaned,
                str(accepted["owner_user_id"]),
                accepted.get("invite_id"),
            ),
        )
        return _row(accepted)


async def delete_contact(bot_id: Any, peer_bot_id: Any) -> bool:
    cleaned = normalize_uuid(str(bot_id)) if bot_id else None
    peer = normalize_uuid(str(peer_bot_id)) if peer_bot_id else None
    if cleaned is None or peer is None:
        return False
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM bot_dm_contacts "
            "WHERE bot_id = %s AND peer_bot_id = %s",
            (cleaned, peer),
        )
        return cur.rowcount > 0


async def block_pair(bot_id: Any, peer_bot_id: Any) -> None:
    """Block both directions: a block must not leave the sender able to reply."""
    cleaned = normalize_uuid(str(bot_id)) if bot_id else None
    peer = normalize_uuid(str(peer_bot_id)) if peer_bot_id else None
    if cleaned is None or peer is None:
        return
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
                UPDATE bot_dm_contacts SET status = 'blocked', updated_at = NOW()
                WHERE (bot_id = %s AND peer_bot_id = %s)
                   OR (bot_id = %s AND peer_bot_id = %s)
                """,
            (cleaned, peer, peer, cleaned),
        )


async def delivery_allowed(to_bot_id: Any, from_bot_id: Any) -> bool:
    """The receiver's consent gate: only its accepted row admits a delivery."""
    cleaned = normalize_uuid(str(to_bot_id)) if to_bot_id else None
    sender = normalize_uuid(str(from_bot_id)) if from_bot_id else None
    if cleaned is None or sender is None:
        return False
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT 1 FROM bot_dm_contacts "
            "WHERE bot_id = %s AND peer_bot_id = %s AND status = 'accepted'",
            (cleaned, sender),
        )
        return (await cur.fetchone()) is not None


async def count_recent_external(from_bot_id: Any, *, seconds: int) -> int:
    cleaned = normalize_uuid(str(from_bot_id)) if from_bot_id else None
    if cleaned is None:
        return 0
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) FROM bot_messages "
            "WHERE external AND from_id = %s "
            "AND created_at > NOW() - make_interval(secs => %s)",
            (str(cleaned), seconds),
        )
        return int((await cur.fetchone())[0])


async def clear_awaiting(to_bot_id: Any, from_bot_id: Any) -> int:
    """Drop the held flag once the receiver accepted, so retries can sweep."""
    cleaned = normalize_uuid(str(to_bot_id)) if to_bot_id else None
    sender = normalize_uuid(str(from_bot_id)) if from_bot_id else None
    if cleaned is None or sender is None:
        return 0
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE bot_messages SET payload = payload - 'awaiting_accept' "
            "WHERE external AND status = 'queued' AND to_bot_id = %s "
            "AND from_id = %s AND payload->>'awaiting_accept' = 'true'",
            (cleaned, str(sender)),
        )
        return cur.rowcount


async def list_awaiting(to_bot_id: Any, from_bot_id: Any) -> list[str]:
    """Queued first messages held behind a pending request."""
    cleaned = normalize_uuid(str(to_bot_id)) if to_bot_id else None
    sender = normalize_uuid(str(from_bot_id)) if from_bot_id else None
    if cleaned is None or sender is None:
        return []
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT message_id::text FROM bot_messages "
            "WHERE external AND status = 'queued' AND to_bot_id = %s "
            "AND from_id = %s AND payload->>'awaiting_accept' = 'true' "
            "ORDER BY created_at",
            (cleaned, str(sender)),
        )
        return [r[0] for r in await cur.fetchall()]


async def fail_awaiting(to_bot_id: Any, from_bot_id: Any) -> int:
    cleaned = normalize_uuid(str(to_bot_id)) if to_bot_id else None
    sender = normalize_uuid(str(from_bot_id)) if from_bot_id else None
    if cleaned is None or sender is None:
        return 0
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE bot_messages SET status = 'failed' "
            "WHERE external AND status = 'queued' AND to_bot_id = %s "
            "AND from_id = %s AND payload->>'awaiting_accept' = 'true'",
            (cleaned, str(sender)),
        )
        return cur.rowcount
