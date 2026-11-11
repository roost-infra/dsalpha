"""The bot-message SQL matches the columns it reads.

``bot_messages.from_id`` is VARCHAR because a user id may be the sender; a
UUID cast in the per-sender rate-limit query made every bot-to-bot send fail
with ``operator does not exist: character varying = uuid``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.server.database import bot_messages


class _Cursor:
    def __init__(self) -> None:
        self.sql = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params):
        self.sql = str(query)

    async def fetchone(self):
        return (0,)


class _Conn:
    def __init__(self) -> None:
        self.cursor_obj = _Cursor()

    def cursor(self):
        return self.cursor_obj

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_the_sender_rate_limit_compares_from_id_as_text():
    conn = _Conn()
    with patch.object(bot_messages, "get_db_connection", return_value=conn):
        count = await bot_messages.count_recent_from("22222222-2222-2222-2222-222222222222")
    assert count == 0
    assert "from_id = %s" in conn.cursor_obj.sql
    assert "from_id = %s::uuid" not in conn.cursor_obj.sql


class _Rows:
    def __init__(self) -> None:
        self.sql = ""
        self.params = ()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params):
        self.sql = str(query)
        self.params = params

    async def fetchall(self):
        return []


class _ListConn:
    def __init__(self, cursor: _Rows) -> None:
        self.cursor_obj = cursor

    def cursor(self, **_kwargs):
        return self.cursor_obj

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_an_inbox_read_keeps_a_computer_to_its_workspaces():
    cursor = _Rows()
    with patch.object(bot_messages, "get_db_connection", lambda conn=None: _ListConn(cursor)):
        assert await bot_messages.list_for_user("u-1", computer_id="c-1") == []
    assert "tb.workspace_id IN (SELECT workspace_id FROM workspaces" in cursor.sql
    assert "c-1" in cursor.params


@pytest.mark.asyncio
async def test_an_inbox_tail_keeps_the_same_computer_scope():
    cursor = _Rows()
    with patch.object(bot_messages, "get_db_connection", lambda conn=None: _ListConn(cursor)):
        assert await bot_messages.list_after(
            "u-1", after="2026-11-10T00:00:00Z", computer_id="c-1"
        ) == []
    assert "computer_id = %s::uuid" in cursor.sql
    assert cursor.params[-2] == "c-1" or "c-1" in cursor.params
