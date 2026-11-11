"""POST /api/v1/threads with a title the caller names.

A thread is born titled: by default with the stamp of its first message, which
the title generator then replaces. A caller may name the title instead, for a
first turn that opens with no message of the user's (the first query is empty,
or is not the user's words): the row stores that title and no generation runs,
so nothing written for the model can become the thread's name.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from src.server.models.conversation import ThreadCreateRequest
from tests.unit.server.app.test_threads_subagents_allowed import _request, _row

CREATE_MOD = "src.server.app.threads.create"


async def _create(body):
    from src.server.services.turn_runtime import TurnRoute

    with (
        patch(f"{CREATE_MOD}.HOST_MODE", "oss"),
        patch(
            f"{CREATE_MOD}.requested_workspace",
            new=AsyncMock(return_value={"workspace_id": "ws-1", "status": "active"}),
        ),
        patch(f"{CREATE_MOD}.turn_route", return_value=TurnRoute("ws-1", "analyst")),
        patch(
            f"{CREATE_MOD}.create_thread", new=AsyncMock(return_value=_row())
        ) as create,
        patch(
            f"{CREATE_MOD}.schedule_title_generation", return_value=None
        ) as generate,
    ):
        resp = await _request("POST", "/api/v1/threads", body)
    return resp, create, generate


@pytest.mark.asyncio
async def test_a_named_title_is_stored_and_nothing_generates_over_it():
    resp, create, generate = await _create({"workspace_id": "ws-1", "title": "Getting started"})

    assert resp.status_code == 201
    assert create.await_args.kwargs["title"] == "Getting started"
    assert resp.json()["title"] == "Getting started"
    generate.assert_not_called()


@pytest.mark.asyncio
async def test_a_named_title_wins_over_the_first_query():
    resp, create, generate = await _create(
        {"workspace_id": "ws-1", "first_query": "hello", "title": "Getting started"}
    )

    assert resp.status_code == 201
    assert create.await_args.kwargs["title"] == "Getting started"
    generate.assert_not_called()


@pytest.mark.asyncio
async def test_without_one_the_first_query_is_stamped_and_generated_from():
    resp, create, generate = await _create({"workspace_id": "ws-1", "first_query": "hello"})

    assert resp.status_code == 201
    assert create.await_args.kwargs["title"] == "hello"
    generate.assert_called_once()
    assert generate.call_args.kwargs["first_query"] == "hello"
    assert generate.call_args.kwargs["expected_title"] == "hello"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"workspace_id": "ws-1"},
        {"workspace_id": "ws-1", "first_query": ""},
        {"workspace_id": "ws-1", "first_query": "", "title": ""},
    ],
    ids=["neither", "blank-query", "blank-both"],
)
async def test_a_create_with_nothing_to_title_it_is_refused(body):
    resp, create, _ = await _create(body)

    assert resp.status_code == 422
    create.assert_not_awaited()


def test_a_named_title_is_capped_like_a_rename():
    with pytest.raises(ValidationError):
        ThreadCreateRequest(title="x" * 256)
    assert ThreadCreateRequest(title="x" * 255).first_query == ""


def test_a_reply_after_a_long_quote_survives_the_clip():
    message = '<quote source="Analyst">' + "word " * 1000 + "</quote>\n<reply>why?</reply>"
    assert ThreadCreateRequest(first_query=message).first_query == message


@pytest.mark.asyncio
async def test_a_named_bot_is_bound_to_the_new_thread():
    bot = {
        "bot_id": "b-1",
        "workspace_id": "ws-1",
        "status": "active",
        "role": "analyst",
    }
    body = {"workspace_id": "ws-1", "bot_id": "b-1", "title": "T"}
    with patch(
        "src.server.database.bots.get_bot_for_user", AsyncMock(return_value=bot)
    ), patch(
        "src.server.database.bots.get_private_thread", AsyncMock(return_value=None)
    ), patch(
        "src.server.database.bots.clear_unusable_primary", AsyncMock()
    ), patch(
        "src.server.database.bots.bind_thread_bot", AsyncMock()
    ) as bind, patch(
        "src.server.database.bots.set_primary_thread", AsyncMock()
    ) as pin:
        resp, create, _ = await _create(body)
    assert resp.status_code == 201
    assert resp.json()["bot_id"] == "b-1"
    create.assert_awaited_once()
    bind.assert_awaited_once()
    assert bind.await_args.kwargs["force"] is True
    pin.assert_awaited_once()


@pytest.mark.asyncio
async def test_opening_a_bot_reuses_its_usable_private_thread():
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    bot = {"bot_id": "b-1", "workspace_id": "ws-1", "status": "active", "role": "analyst"}
    existing = {
        "conversation_thread_id": "t-existing",
        "workspace_id": "ws-1",
        "thread_index": 4,
        "title": "Quant",
        "msg_type": "ptc",
        "subagents_allowed": None,
        "reasoning_effort": None,
        "fast_mode": None,
        "created_at": now,
        "updated_at": now,
    }
    body = {"workspace_id": "ws-1", "bot_id": "b-1", "title": "Ignored"}
    with patch(
        "src.server.database.bots.get_bot_for_user", AsyncMock(return_value=bot)
    ), patch(
        "src.server.database.bots.get_private_thread", AsyncMock(return_value="t-existing")
    ), patch(
        "src.server.app.threads.create.get_thread_by_id", AsyncMock(return_value=existing)
    ), patch(
        "src.server.database.bots.clear_unusable_primary", AsyncMock()
    ) as clear, patch(
        "src.server.database.bots.bind_thread_bot", AsyncMock()
    ) as bind:
        resp, create, generate = await _create(body)
    assert resp.status_code == 201
    assert resp.json()["thread_id"] == "t-existing"
    assert resp.json()["title"] == "Quant"
    assert resp.json()["bot_id"] == "b-1"
    create.assert_not_awaited()
    bind.assert_not_awaited()
    clear.assert_not_awaited()
    generate.assert_not_called()


@pytest.mark.asyncio
async def test_a_paused_bot_cannot_be_named_for_a_new_thread():
    bot = {
        "bot_id": "b-1",
        "workspace_id": "ws-1",
        "status": "paused",
        "role": "analyst",
    }
    body = {"workspace_id": "ws-1", "bot_id": "b-1", "title": "T"}
    with patch(
        "src.server.database.bots.get_bot_for_user", AsyncMock(return_value=bot)
    ):
        resp, create, _ = await _create(body)
    assert resp.status_code == 409
    create.assert_not_awaited()
