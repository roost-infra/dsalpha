"""A bot messages a bot of its own workspace, and a cycle is refused.

The tool writes one durable row and then posts it; the tests pin the routing
decisions (self, unknown, paused target, waiting-on-you) because each of them
is a loop or a misdelivery if it slips.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.tools.bots.tool import list_assignments, list_bots, report_to, send_bot_message

USER = "user-1"
WS = "22222222-2222-2222-2222-222222222222"
THREAD = "11111111-1111-1111-1111-111111111111"
CALLER = {"bot_id": "b-1", "name": "Quant", "role": "analyst", "workspace_id": WS, "status": "active"}
TARGET = {"bot_id": "b-2", "name": "Scout", "role": "analyst", "workspace_id": WS, "status": "active"}

CONFIG = {"configurable": {"user_id": USER, "workspace_id": WS, "thread_id": THREAD}}


def _call(args: dict) -> dict:
    """A send_bot_message call as the graph makes one (the id is injected)."""
    return {
        "name": "send_bot_message",
        "args": args,
        "id": "call_1",
        "type": "tool_call",
    }


async def _invoke(tool, args: dict) -> str:
    """Invoke with a full tool call and return the text the model would read."""
    call = {**_call(args), "name": tool.name}
    result = await tool.ainvoke(call, config=CONFIG)
    return result.content if hasattr(result, "content") else str(result)


async def _say(args: dict) -> str:
    return await _invoke(send_bot_message, args)


def _ctx():
    return patch.multiple(
        "src.server.database.bots",
        list_bots=AsyncMock(return_value=[CALLER, TARGET]),
        get_thread_bot_id=AsyncMock(return_value="b-1"),
        get_bot=AsyncMock(return_value=CALLER),
    )


@pytest.mark.asyncio
async def test_the_roster_marks_the_speaking_bot():
    with _ctx():
        out = await list_bots.ainvoke({}, config=CONFIG)
    assert "Quant" in out and "you" in out
    assert "Scout" in out
    assert "b-2" in out


@pytest.mark.asyncio
async def test_a_message_is_written_and_delivered():
    with _ctx(), patch(
        "src.server.database.assignments.open_assignment_targets",
        AsyncMock(return_value=set()),
    ), patch(
        "src.server.database.bot_messages.create_message",
        AsyncMock(return_value=({"message_id": "m-1"}, True)),
    ) as create, patch(
        "src.server.services.bot_messages.delivery.deliver_message",
        AsyncMock(return_value={"status": "delivered", "thread_id": "t-1", "outcome": "dispatched"}),
    ), patch(
        "src.server.database.assignments.create_assignment",
        AsyncMock(side_effect=AssertionError("a plain message is not an assignment")),
    ):
        out = await _say({"to": "Scout", "content": "check the filings"})
    assert "delivered to Scout" in out
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_request_creates_an_assignment():
    assignment = {"assignment_id": "a-1"}
    with _ctx(), patch(
        "src.server.database.assignments.open_assignment_targets",
        AsyncMock(return_value=set()),
    ), patch(
        "src.server.database.assignments.create_assignment",
        AsyncMock(return_value=assignment),
    ) as make, patch(
        "src.server.database.bot_messages.create_message",
        AsyncMock(return_value=({"message_id": "m-1"}, True)),
    ) as create, patch(
        "src.server.services.bot_messages.delivery.deliver_message",
        AsyncMock(return_value={"status": "queued", "thread_id": None, "outcome": "cap"}),
    ):
        out = await _say({"to": "Scout", "content": "do it", "kind": "request"})
    assert "queued for Scout" in out
    make.assert_awaited_once()
    assert create.call_args.kwargs["payload"] == {"assignment_id": "a-1"}


@pytest.mark.asyncio
async def test_a_bot_cannot_message_itself():
    with _ctx():
        out = await _say({"to": "Quant", "content": "hi"})
    assert out.startswith("refused")
    assert "that is you" in out


@pytest.mark.asyncio
async def test_an_unknown_target_is_refused():
    with _ctx():
        out = await _say({"to": "Nobody", "content": "hi"})
    assert out.startswith("refused")
    assert "no bot" in out


@pytest.mark.asyncio
async def test_messaging_a_bot_that_waits_on_you_is_refused():
    with _ctx(), patch(
        "src.server.database.assignments.open_assignment_targets",
        AsyncMock(return_value={"b-1"}),
    ):
        out = await _say({"to": "Scout", "content": "hi"})
    assert out.startswith("refused")
    assert "waiting on your answer" in out


@pytest.mark.asyncio
async def test_a_paused_target_is_reported_not_silently_lost():
    paused = {**TARGET, "status": "paused"}
    with patch.multiple(
        "src.server.database.bots",
        list_bots=AsyncMock(return_value=[CALLER, paused]),
        get_thread_bot_id=AsyncMock(return_value="b-1"),
        get_bot=AsyncMock(return_value=CALLER),
    ), patch(
        "src.server.database.assignments.open_assignment_targets",
        AsyncMock(return_value=set()),
    ), patch(
        "src.server.database.bot_messages.create_message",
        AsyncMock(return_value=({"message_id": "m-1"}, True)),
    ), patch(
        "src.server.services.bot_messages.delivery.deliver_message",
        AsyncMock(return_value={"status": "failed", "thread_id": None, "outcome": "target_paused"}),
    ):
        out = await _say({"to": "Scout", "content": "hi"})
    assert out.startswith("refused")
    assert "target_paused" in out


# --- closing the loop: report_to / list_assignments -----------------------

ASSIGNMENT = {
    "assignment_id": "a-1",
    "from_bot_id": "b-2",
    "to_bot_id": "b-1",
    "thread_id": THREAD,
    "status": "working",
    "outcome": None,
    "evidence": [],
}


@pytest.mark.asyncio
async def test_reporting_closes_the_assignment_and_notifies_the_requester():
    with _ctx(), patch(
        "src.server.database.assignments.get_assignment",
        AsyncMock(return_value=dict(ASSIGNMENT)),
    ), patch(
        "src.server.database.assignments.update_assignment",
        AsyncMock(return_value={"status": "done"}),
    ) as close, patch(
        "src.server.database.bot_messages.create_message",
        AsyncMock(return_value=({"message_id": "m-2"}, True)),
    ) as make, patch(
        "src.server.services.bot_messages.delivery.deliver_message",
        AsyncMock(return_value={"status": "delivered"}),
    ):
        out = await _invoke(
            report_to, {"assignment_id": "a-1", "outcome": "done", "evidence": "report.pdf"}
        )
    assert out.startswith("reported")
    close.assert_awaited_once()
    assert close.await_args.kwargs["status"] == "done"
    assert make.await_args.kwargs["kind"] == "report"


@pytest.mark.asyncio
async def test_an_assignment_you_were_not_given_is_refused():
    with _ctx(), patch(
        "src.server.database.assignments.get_assignment",
        AsyncMock(return_value={**ASSIGNMENT, "to_bot_id": "someone-else"}),
    ):
        out = await _invoke(report_to, {"assignment_id": "a-1", "outcome": "done"})
    assert out.startswith("refused")


@pytest.mark.asyncio
async def test_listing_assignments_marks_which_side_you_are():
    rows = [
        {**ASSIGNMENT, "assignment_id": "a-1"},
        {**ASSIGNMENT, "assignment_id": "a-2", "from_bot_id": "b-1", "to_bot_id": "b-2"},
    ]
    with _ctx(), patch(
        "src.server.database.assignments.list_assignments",
        AsyncMock(return_value=rows),
    ):
        out = await _invoke(list_assignments, {})
    assert "you →" in out
    assert "→ you" in out
