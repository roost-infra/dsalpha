"""A shared chat is not a bot's private thread.

Delivery and ``POST /threads`` pin with COALESCE, so a pointer at a shared
or archived thread has to be dropped, and the fallback search must not
adopt that chat either.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.server.database import bots


class _Cursor:
    def __init__(self, sql: list[str]) -> None:
        self.sql = sql

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params):
        self.sql.append(str(query))

    async def fetchone(self):
        return None


class _Conn:
    def __init__(self, sql: list[str]) -> None:
        self.sql = sql

    def cursor(self, **_kwargs):
        return _Cursor(self.sql)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_find_private_thread_does_not_adopt_a_shared_chat():
    sql: list[str] = []

    def connect(conn=None):
        return _Conn(sql)

    with patch.object(bots, "get_db_connection", connect):
        assert await bots.find_private_thread(
            "11111111-1111-1111-1111-111111111111"
        ) is None
    assert sql
    assert "is_shared IS NOT TRUE" in sql[0]
    assert "archived_at IS NULL" in sql[0]
    assert "bt.kind = 'private'" in sql[0]


@pytest.mark.asyncio
async def test_an_unusable_primary_pointer_is_cleared():
    sql: list[str] = []

    def connect(conn=None):
        return _Conn(sql)

    with patch.object(bots, "get_db_connection", connect):
        await bots.clear_unusable_primary("11111111-1111-1111-1111-111111111111")
    assert "primary_thread_id = NULL" in sql[0]
    assert "is_shared IS NOT TRUE" in sql[0]
    assert "archived_at IS NULL" in sql[0]
