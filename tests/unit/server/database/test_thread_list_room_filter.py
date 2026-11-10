"""User-facing thread lists leave room-member threads out.

A room member answers in its own thread, but that thread is the member's
context boundary, not a conversation the user started: listing it put one
untitled row per bot in the sidebar (and the room page is where it is read).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.server.database.conversation import threads_read


class _Cursor:
    def __init__(self, sql: list[str], rows: list | None = None) -> None:
        self.sql = sql
        self.rows = rows or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params):
        self.sql.append(str(query))

    async def fetchone(self):
        return {"total": 0}

    async def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, sql: list[str], rows: list) -> None:
        self.sql = sql
        self.rows = rows

    def cursor(self, **_kwargs):
        return _Cursor(self.sql, self.rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, rows: list | None = None) -> None:
        self.sql: list[str] = []
        self.rows = rows if rows is not None else []

    def get_db_connection(self):
        return _Conn(self.sql, self.rows)


@pytest.mark.asyncio
async def test_workspace_list_excludes_room_member_threads():
    fake = _Pool()
    with patch.object(threads_read.pool, "get_db_connection", fake.get_db_connection):
        rows, total = await threads_read.get_workspace_threads("ws-1")
    assert rows == [] and total == 0
    assert len(fake.sql) == 2
    for query in fake.sql:
        assert "bot_threads" in query
        assert "bt.kind = 'room'" in query


@pytest.mark.asyncio
async def test_cross_workspace_list_excludes_room_member_threads():
    fake = _Pool()
    with patch.object(threads_read.pool, "get_db_connection", fake.get_db_connection):
        rows, total = await threads_read.get_threads_for_user("u-1")
    assert rows == [] and total == 0
    assert len(fake.sql) == 2
    for query in fake.sql:
        assert "bot_threads" in query
        assert "bt.kind = 'room'" in query


def _assert_room_hidden(queries: list[str]) -> None:
    assert queries
    for query in queries:
        assert "bot_threads" in query
        assert "bt.kind = 'room'" in query


@pytest.mark.asyncio
async def test_recents_hide_room_member_threads():
    fake = _Pool()
    with patch.object(threads_read.pool, "get_db_connection", fake.get_db_connection):
        assert await threads_read.get_recent_threads_for_user("u-1") == []
    _assert_room_hidden(fake.sql)


@pytest.mark.asyncio
async def test_the_lifecycle_feed_hides_room_member_threads():
    fake = _Pool()
    with patch.object(threads_read.pool, "get_db_connection", fake.get_db_connection):
        rows, seq = await threads_read.get_thread_lifecycle_rows("u-1")
    assert rows == [] and seq == 0
    _assert_room_hidden(fake.sql)


@pytest.mark.asyncio
async def test_the_computer_thread_index_hides_room_member_threads():
    fake = _Pool([{"digest": "abc"}])
    with patch.object(threads_read.pool, "get_db_connection", fake.get_db_connection):
        digest, rows = await threads_read.list_computer_threads("c-1")
    assert digest == "abc" and rows == []
    _assert_room_hidden(fake.sql)
