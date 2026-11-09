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
