"""The account's connected-app installation (migration 120).

A user's Composio project session is long-lived; the row remembers which
Composio user and Tool Router session the account owns so a reload reuses the
same connections instead of minting a new user and losing every grant.
"""

from __future__ import annotations

from typing import Any, Optional

from psycopg.rows import dict_row

from src.server.database.pool import get_db_connection


def _row(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    out = dict(row)
    for key in ("created_at", "updated_at"):
        value = out.get(key)
        if value is not None and hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


async def get_installation(user_id: str, *, conn=None) -> dict[str, Any] | None:
    async with get_db_connection(conn) as owned:
        async with owned.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM connected_app_installations WHERE user_id = %s",
                (user_id,),
            )
            return _row(await cur.fetchone())


async def save_installation(
    user_id: str,
    *,
    composio_user_id: str,
    session_id: str,
    mcp_url: str,
    proxy_token_hash: Optional[str] = None,
    conn=None,
) -> dict[str, Any]:
    async with get_db_connection(conn) as owned:
        async with owned.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO connected_app_installations
                    (user_id, composio_user_id, session_id, mcp_url, proxy_token_hash)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    composio_user_id = EXCLUDED.composio_user_id,
                    session_id = EXCLUDED.session_id,
                    mcp_url = EXCLUDED.mcp_url,
                    proxy_token_hash = EXCLUDED.proxy_token_hash,
                    updated_at = NOW()
                RETURNING *
                """,
                (user_id, composio_user_id, session_id, mcp_url, proxy_token_hash),
            )
            return _row(await cur.fetchone()) or {}


async def get_installation_by_proxy_token(
    token_hash: str, *, conn=None
) -> dict[str, Any] | None:
    async with get_db_connection(conn) as owned:
        async with owned.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM connected_app_installations "
                "WHERE proxy_token_hash = %s",
                (token_hash,),
            )
            return _row(await cur.fetchone())


async def delete_installation(user_id: str, *, conn=None) -> None:
    async with get_db_connection(conn) as owned:
        async with owned.cursor() as cur:
            await cur.execute(
                "DELETE FROM connected_app_installations WHERE user_id = %s",
                (user_id,),
            )
