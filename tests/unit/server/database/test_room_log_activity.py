"""A room message moves the room in the recency-ordered conversation stream.

``updated_at`` used to change only on a name, host, membership or bulletin
edit, so a busy room sat still until someone edited it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from src.server.database import rooms

ROOM = "22222222-2222-2222-2222-222222222222"


class _Cursor:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self._inserted = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params):
        self.sql.append(str(query))

    async def fetchone(self):
        if self._inserted:
            return None
        self._inserted = True
        return {
            "room_id": ROOM,
            "seq": 1,
            "round_id": None,
            "sender_type": "user",
            "sender_id": "u",
            "kind": "message",
            "content": "hello",
            "metadata": {},
            "created_at": datetime.now(UTC),
        }


class _Conn:
    def __init__(self, cursor: _Cursor) -> None:
        self.cursor_obj = cursor

    def cursor(self, **_kwargs):
        return self.cursor_obj

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_appending_a_message_bumps_the_room_updated_at():
    cursor = _Cursor()
    with patch.object(rooms, "get_db_connection", lambda conn=None: _Conn(cursor)):
        row = await rooms.append_log(
            ROOM, sender_type="user", sender_id="u", content="hello"
        )
    assert row is not None and row["seq"] == 1
    assert any("INSERT INTO room_log" in sql for sql in cursor.sql)
    assert any(
        "UPDATE rooms SET updated_at = NOW()" in sql for sql in cursor.sql
    )


@pytest.mark.asyncio
async def test_a_conflicting_append_does_not_move_the_room():
    cursor = _Cursor()
    cursor._inserted = True  # fetchone returns no row
    with patch.object(rooms, "get_db_connection", lambda conn=None: _Conn(cursor)):
        assert await rooms.append_log(
            ROOM,
            sender_type="bot",
            sender_id=ROOM,
            content="dup",
            ignore_conflict=True,
        ) is None
    assert not any("UPDATE rooms" in sql for sql in cursor.sql)
