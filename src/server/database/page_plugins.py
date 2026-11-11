"""Storage for the built-in page plugins a user has switched on."""

from __future__ import annotations

from typing import Any, Dict, List

from psycopg.rows import dict_row

from src.server.database.pool import get_db_connection

#: The page plugins this build can offer. The frontend ships their manifests;
#: the backend only records the switch and refuses unknown ids, so a stale
#: client cannot grow the table with arbitrary names.
PAGE_PLUGIN_IDS: tuple[str, ...] = ("market-center",)


async def list_user_page_plugins(user_id: str) -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT plugin_id, enabled, updated_at "
                "FROM user_page_plugins WHERE user_id = %s",
                (user_id,),
            )
            return list(await cur.fetchall())


async def set_user_page_plugin(
    user_id: str, plugin_id: str, enabled: bool
) -> Dict[str, Any]:
    async with get_db_connection() as conn, conn.transaction():
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO user_page_plugins (user_id, plugin_id, enabled, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (user_id, plugin_id) DO UPDATE SET
                    enabled = EXCLUDED.enabled,
                    updated_at = NOW()
                RETURNING plugin_id, enabled, updated_at
                """,
                (user_id, plugin_id, enabled),
            )
            return await cur.fetchone()
