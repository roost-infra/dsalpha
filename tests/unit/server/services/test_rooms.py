"""Rooms: who speaks, in which order, and what a member is handed.

The round decisions are pure functions here; the driver's DB and turn posting
are exercised by the app-level tests and the sweeper's own contract.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.server.services.rooms.context import is_pass, render_member_context
from src.server.services.rooms.coordinator import (
    _initial_slots,
    parse_mentions,
    start_round,
)

HOST = {"bot_id": "b-host", "name": "Chief", "room_role": "host", "status": "active", "workspace_id": "ws"}
A = {"bot_id": "b-a", "name": "数据官", "room_role": "member", "status": "active", "workspace_id": "ws"}
B = {"bot_id": "b-b", "name": "数据官2", "room_role": "member", "status": "active", "workspace_id": "ws"}
PAUSED = {"bot_id": "b-p", "name": "Sleepy", "room_role": "member", "status": "paused", "workspace_id": "ws"}
ROOM = {"room_id": "r-1", "name": "Research", "responder": "everyone", "bulletin": "One short message each."}


def test_everyone_speaks_host_first_and_paused_members_are_left_out():
    slots = _initial_slots(ROOM, [A, PAUSED, HOST, B], "hello")
    assert [s["bot_id"] for s in slots] == ["b-host", "b-a", "b-b"]


def test_mentions_responder_keeps_only_the_named_member():
    room = {**ROOM, "responder": "mentions"}
    slots = _initial_slots(room, [A, HOST], "@数据官 take this")
    assert [s["bot_id"] for s in slots] == ["b-a"]


def test_mentions_with_nobody_named_falls_back_to_everyone():
    room = {**ROOM, "responder": "mentions"}
    slots = _initial_slots(room, [A, HOST], "no mention here")
    assert [s["bot_id"] for s in slots] == ["b-host", "b-a"]


def test_a_named_responder_bot_speaks_alone():
    room = {**ROOM, "responder": "member:b-a"}
    slots = _initial_slots(room, [A, HOST], "hi")
    assert [s["bot_id"] for s in slots] == ["b-a"]


def test_mentions_use_the_longest_name_and_need_a_boundary():
    members = [A, B]
    # 数据官2 is a different bot from 数据官; the longer name wins.
    assert parse_mentions("@数据官2 please", members) == ["b-b"]
    # A bare prefix of the longer name is not a mention of either.
    assert parse_mentions("@数据官3 please", members) == []
    assert parse_mentions("@数据官，请", members) == ["b-a"]
    assert parse_mentions("@数据官 and @数据官2", members) == ["b-a", "b-b"]


def test_pass_is_recognised_in_the_shapes_a_model_uses():
    assert is_pass("[PASS]")
    assert is_pass(" [PASS] ")
    assert is_pass("[pass]")
    assert not is_pass("pass")
    assert not is_pass("I'll pass on that")


def test_the_member_context_carries_the_room_its_increments_and_its_turn():
    text = render_member_context(
        ROOM,
        [HOST, A],
        A,
        earlier=[{"seq": 1, "sender_type": "user", "sender_id": "u", "content": "old"}],
        increments=[
            {"seq": 2, "sender_type": "user", "sender_id": "u", "content": "new question"},
            {"seq": 3, "sender_type": "bot", "sender_id": "b-host", "content": "on it"},
        ],
        order_index=1,
        order_total=2,
    )
    assert '[Group chat "Research"]' in text
    assert "数据官" in text
    assert "Announcement:" in text
    assert "[2] the user: new question" in text
    assert "You speak 2 of 2" in text
    assert "[PASS]" in text


@pytest.mark.asyncio
async def test_a_user_message_opens_a_round_when_none_is_live():
    room = {"room_id": "r-1", "user_id": "u-1", "name": "R", "responder": "everyone"}
    created = {"round_id": "round-1", "status": "queued", "slots": []}
    with patch(
        "src.server.services.rooms.coordinator.room_db.append_log",
        AsyncMock(return_value={"seq": 7}),
    ), patch(
        "src.server.services.rooms.coordinator.room_db.active_round",
        AsyncMock(return_value=None),
    ), patch(
        "src.server.services.rooms.coordinator.room_db.list_members_with_bots",
        AsyncMock(return_value=[HOST, A]),
    ), patch(
        "src.server.services.rooms.coordinator.room_db.create_round",
        AsyncMock(return_value=created),
    ) as make, patch(
        "src.server.services.rooms.coordinator.schedule_start"
    ) as schedule:
        result = await start_round(room, "hello", user_id="u-1")
    assert result["round"]["round_id"] == "round-1"
    assert result["message"]["seq"] == 7
    make.assert_awaited_once()
    schedule.assert_called_once()


@pytest.mark.asyncio
async def test_a_message_during_a_live_round_joins_it_instead_of_opening_another():
    room = {"room_id": "r-1", "user_id": "u-1", "name": "R", "responder": "everyone"}
    live = {"round_id": "round-live", "status": "running"}
    with patch(
        "src.server.services.rooms.coordinator.room_db.append_log",
        AsyncMock(return_value={"seq": 8}),
    ), patch(
        "src.server.services.rooms.coordinator.room_db.active_round",
        AsyncMock(return_value=live),
    ), patch(
        "src.server.services.rooms.coordinator.room_db.create_round",
        AsyncMock(side_effect=AssertionError("must not open a second round")),
    ), patch(
        "src.server.services.rooms.coordinator.schedule_start"
    ):
        result = await start_round(room, "another point", user_id="u-1")
    assert result["round"]["round_id"] == "round-live"


@pytest.mark.asyncio
async def test_a_round_walks_its_slots_logs_answers_and_finishes():
    from src.server.services.rooms import coordinator

    slots0 = [
        {"bot_id": "b-a", "name": "数据官", "state": "pending"},
        {"bot_id": "b-host", "name": "Chief", "state": "pending"},
    ]
    slots1 = [slots0[0], {**slots0[1], "state": "pending"}]
    rounds = [
        {"round_id": "r-1", "room_id": "r-1", "status": "running", "slots": slots0, "slot_cursor": 0, "start_seq": 1},
        {"round_id": "r-1", "room_id": "r-1", "status": "running", "slots": [{**slots0[0], "state": "done"}, slots0[1]], "slot_cursor": 1, "start_seq": 1},
        {"round_id": "r-1", "room_id": "r-1", "status": "running", "slots": [{**slots0[0], "state": "done"}, {**slots0[1], "state": "done"}], "slot_cursor": 2, "start_seq": 1},
    ]
    room = {"room_id": "r-1", "user_id": "u-1", "name": "R", "responder": "everyone"}
    with patch.object(coordinator.room_db, "claim_round", AsyncMock(return_value=True)), \
         patch.object(coordinator.room_db, "get_round", AsyncMock(side_effect=rounds)), \
         patch.object(coordinator.room_db, "get_room", AsyncMock(return_value=room)), \
         patch.object(coordinator.room_db, "list_members_with_bots", AsyncMock(return_value=[HOST, A])), \
         patch.object(coordinator, "ensure_room_thread", AsyncMock(return_value="th-1")), \
         patch.object(coordinator.room_db, "seen_seq", AsyncMock(return_value=0)), \
         patch.object(coordinator.room_db, "read_log", AsyncMock(return_value=[])), \
         patch.object(coordinator.room_db, "read_log_before", AsyncMock(return_value=[])), \
         patch.object(coordinator.room_db, "save_round_progress", AsyncMock()) as save, \
         patch.object(coordinator.room_db, "set_seen", AsyncMock()) as seen, \
         patch.object(coordinator.room_db, "append_log", AsyncMock(side_effect=lambda *a, **k: {"seq": 10 + random_seq()})) as log, \
         patch.object(coordinator.room_db, "finish_round", AsyncMock()) as finish, \
         patch.object(coordinator, "_wait_terminal", AsyncMock(return_value="completed")), \
         patch.object(coordinator, "latest_run_reply", AsyncMock(side_effect=[{"text": "answer one"}, {"text": "[PASS]"}])), \
         patch("src.server.services.report_back.notify_turn.post_notification_turn", AsyncMock(return_value=("dispatched", "run-1"))):
        await coordinator.drive_round("r-1")

    assert any(
        call.kwargs.get("content") == "answer one"
        for call in log.await_args_list
    ), "the answer must reach the shared log"
    finish.assert_awaited_once()
    assert save.await_count >= 2
    assert seen.await_count == 1


_SEQ = {"n": 10}


def random_seq() -> int:
    _SEQ["n"] += 1
    return _SEQ["n"]
