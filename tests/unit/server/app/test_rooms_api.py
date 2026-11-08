"""The Rooms API's guards: workspace ownership, member scope, archived rooms."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.server.app.rooms import create_room, read_log, send_message
from src.server.models.room import RoomCreate, RoomMessageCreate

USER = "u-1"
WS = "22222222-2222-2222-2222-222222222222"


def _bot(workspace_id: str = WS) -> dict:
    return {"bot_id": "b-1", "name": "Quant", "workspace_id": workspace_id, "status": "active"}


@pytest.mark.asyncio
async def test_a_member_of_another_workspace_is_refused():
    body = RoomCreate(
        workspace_id=WS,
        name="R",
        member_bot_ids=["33333333-3333-3333-3333-333333333333"],
    )
    with patch(
        "src.server.app.rooms._own_workspace", AsyncMock(return_value={"workspace_id": WS})
    ), patch(
        "src.server.app.rooms.bot_db.get_bot_for_user",
        AsyncMock(return_value=_bot("other-ws")),
    ):
        with pytest.raises(HTTPException) as caught:
            await create_room(USER, body)
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_an_archived_room_takes_no_message():
    room = {"room_id": "r-1", "user_id": USER, "workspace_id": WS, "status": "archived"}
    with patch("src.server.app.rooms._owned_room", AsyncMock(return_value=room)), patch(
        "src.server.app.rooms.start_round", AsyncMock()
    ) as start:
        with pytest.raises(HTTPException) as caught:
            await send_message(USER, "r-1", RoomMessageCreate(content="hi"))
    assert caught.value.status_code == 409
    start.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_log_reads_from_a_seq_and_reports_the_tail():
    room = {"room_id": "r-1", "user_id": USER, "workspace_id": WS, "status": "active"}
    entries = [
        {
            "seq": 3,
            "room_id": "r-1",
            "round_id": None,
            "sender_type": "user",
            "sender_id": USER,
            "kind": "message",
            "content": "hello",
            "created_at": None,
        }
    ]
    with patch("src.server.app.rooms._owned_room", AsyncMock(return_value=room)), patch(
        "src.server.app.rooms.room_db.read_log", AsyncMock(return_value=entries)
    ), patch("src.server.app.rooms.room_db.latest_seq", AsyncMock(return_value=3)):
        answer = await read_log(USER, "r-1", since_seq=2, limit=100)
    assert answer.latest_seq == 3
    assert answer.entries[0].content == "hello"


@pytest.mark.asyncio
async def test_a_member_row_carries_the_bots_avatar():
    from src.server.app.rooms import _view

    room = {
        "room_id": "r-1",
        "workspace_id": WS,
        "name": "R",
        "responder": "everyone",
        "bulletin": "",
        "status": "active",
    }
    members = [
        {
            "bot_id": "b-1",
            "name": "Quant",
            "role": "analyst",
            "status": "active",
            "room_role": "host",
            "avatar": {"kind": "mark", "color": "teal"},
        }
    ]
    with patch(
        "src.server.app.rooms.room_db.list_members_with_bots",
        AsyncMock(return_value=members),
    ):
        view = await _view(room)
    assert view.members[0].avatar == {"kind": "mark", "color": "teal"}
