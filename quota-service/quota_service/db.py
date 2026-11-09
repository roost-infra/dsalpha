"""Postgres access: one shared pool, plus a tiny SQL-script runner for the schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_pool: Optional[AsyncConnectionPool] = None


async def init_pool(database_url: str) -> AsyncConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    _pool = AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"row_factory": dict_row},
    )
    await _pool.open()
    await _pool.wait()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("database pool is not initialized")
    return _pool


async def fetch_one(sql: str, params: Any = None) -> Optional[dict]:
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()


async def fetch_all(sql: str, params: Any = None) -> list[dict]:
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def execute(sql: str, params: Any = None) -> int:
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return cur.rowcount


async def run_sql_script(path: Path) -> None:
    """Apply an idempotent SQL script (our schema uses IF NOT EXISTS throughout).

    psycopg's extended protocol accepts one statement per execute, so the file
    is split on semicolons. The schema deliberately contains no semicolons
    inside string literals; keep it that way.
    """
    statements = [s.strip() for s in path.read_text().split(";") if s.strip()]
    async with pool().connection() as conn:
        # A pool connection is not autocommit; without this block every CREATE
        # is rolled back when the connection is returned.
        async with conn.transaction():
            for statement in statements:
                if _comment_only(statement):
                    continue
                await conn.execute(statement)


def _comment_only(statement: str) -> bool:
    return all(
        not line.strip() or line.strip().startswith("--")
        for line in statement.splitlines()
    )


async def in_transaction(conn: AsyncConnection, fn):
    """Run ``fn(cur)`` inside a transaction on an existing connection."""
    async with conn.transaction():
        async with conn.cursor() as cur:
            return await fn(cur)
