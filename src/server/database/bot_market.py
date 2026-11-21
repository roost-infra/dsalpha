"""The built-in Bot market's install journal (migration 119).

The catalogue is shipped with the build, so this module only persists where a
user installed one of those templates: which template and version, into which
workspace, and which Bot row the install created. It is append-only; the live
thing is the Bot row the install wrote.
"""

from __future__ import annotations

from typing import Any, Optional

from psycopg.rows import dict_row

from src.server.database.pool import get_db_connection


def _serialize(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    out = dict(row)
    for key in ("install_id", "workspace_id", "bot_id"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    created = out.get("created_at")
    if created is not None and hasattr(created, "isoformat"):
        out["created_at"] = created.isoformat()
    return out


async def record_install(
    *,
    user_id: str,
    slug: str,
    version: str,
    workspace_id: str,
    bot_id: str,
    conn=None,
) -> dict[str, Any]:
    """Append one install row and return it (with its generated id)."""
    async with get_db_connection(conn) as owned:
        async with owned.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO bot_market_installs
                    (user_id, listing_slug, listing_version, workspace_id, bot_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING install_id, created_at
                """,
                (user_id, slug, version, workspace_id, bot_id),
            )
            row = await cur.fetchone()
    return _serialize(row) or {}


async def installed_slugs(user_id: str, *, conn=None) -> set[str]:
    """The templates this user has installed at least once."""
    async with get_db_connection(conn) as owned:
        async with owned.cursor() as cur:
            await cur.execute(
                "SELECT DISTINCT listing_slug FROM bot_market_installs WHERE user_id = %s",
                (user_id,),
            )
            return {str(row[0]) for row in await cur.fetchall()}


async def list_installs(user_id: str, *, conn=None) -> list[dict[str, Any]]:
    """This user's installs, newest first, with the Bot and workspace names.

    The names are read from the rows the install created, so a Bot renamed
    later reads as its current name; a deleted Bot takes its row with it
    (``ON DELETE CASCADE``), which is exactly when the install journal stops
    naming a live Bot.
    """
    async with get_db_connection(conn) as owned:
        async with owned.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT i.install_id, i.listing_slug AS slug,
                       i.listing_version AS version,
                       i.workspace_id, w.name AS workspace_name,
                       i.bot_id, b.name AS bot_name,
                       i.created_at
                FROM bot_market_installs i
                JOIN workspaces w ON w.workspace_id = i.workspace_id
                JOIN bots b ON b.bot_id = i.bot_id
                WHERE i.user_id = %s
                ORDER BY i.created_at DESC
                """,
                (user_id,),
            )
            return [_serialize(dict(row)) or {} for row in await cur.fetchall()]


async def installs_for_slug(
    user_id: str, slug: str, *, conn=None
) -> list[dict[str, Any]]:
    """This user's installs of one template, newest first (detail page)."""
    async with get_db_connection(conn) as owned:
        async with owned.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT i.install_id, i.workspace_id, w.name AS workspace_name,
                       i.bot_id, b.name AS bot_name
                FROM bot_market_installs i
                JOIN workspaces w ON w.workspace_id = i.workspace_id
                JOIN bots b ON b.bot_id = i.bot_id
                WHERE i.user_id = %s AND i.listing_slug = %s
                ORDER BY i.created_at DESC
                """,
                (user_id, slug),
            )
            return [_serialize(dict(row)) or {} for row in await cur.fetchall()]
