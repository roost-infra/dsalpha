"""The Bots API: the derived Chief of Staff is in every roster, and guards hold.

The list is the one place the Home bot is made without a Home turn, because
the Bots screen has to show it; a workspace-filtered read makes nothing. The
hand-made-only rules (no second bot in Home, no delete of the derived one)
are refused rather than silently allowed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.server.app.bots import delete_bot, list_bots
from src.server.models.bot import BotCreate

USER = "u-1"
WS = "22222222-2222-2222-2222-222222222222"
HOME = "33333333-3333-3333-3333-333333333333"


def _bot(bot_id: str, role: str = "analyst", workspace_id: str = WS) -> dict:
    return {
        "bot_id": bot_id,
        "user_id": USER,
        "workspace_id": workspace_id,
        "name": "Quant" if role == "analyst" else "Chief of Staff",
        "role": role,
        "persona": "",
        "avatar": {},
        "provider": None,
        "model": None,
        "skills": [],
        "tools_allow": [],
        "tools_deny": [],
        "approval": "ask",
        "memory_scopes": ["workspace"],
        "status": "active",
        "primary_thread_id": None,
        "created_at": None,
        "updated_at": None,
    }


@pytest.mark.asyncio
async def test_an_unfiltered_list_makes_the_derived_chief_of_staff():
    home = _bot("b-home", role="chief_of_staff", workspace_id=HOME)
    with patch(
        "src.server.app.bots.bot_db.ensure_home_bot", AsyncMock(return_value=home)
    ) as ensure, patch(
        "src.server.app.bots.bot_db.list_bots", AsyncMock(return_value=[home])
    ):
        answer = await list_bots(USER, None)
    ensure.assert_awaited_once_with(USER)
    assert [b.role for b in answer.bots] == ["chief_of_staff"]


@pytest.mark.asyncio
async def test_a_filtered_list_makes_nothing():
    workspace = {"workspace_id": WS, "user_id": USER}
    with patch(
        "src.server.app.bots._own_workspace", AsyncMock(return_value=workspace)
    ), patch(
        "src.server.app.bots.bot_db.ensure_home_bot", AsyncMock()
    ) as ensure, patch(
        "src.server.app.bots.bot_db.list_bots", AsyncMock(return_value=[])
    ):
        answer = await list_bots(USER, workspace_id=WS)
    ensure.assert_not_awaited()
    assert answer.bots == []


@pytest.mark.asyncio
async def test_the_derived_chief_of_staff_cannot_be_deleted():
    home = _bot("b-home", role="chief_of_staff", workspace_id=HOME)
    with patch("src.server.app.bots._owned_bot", AsyncMock(return_value=home)):
        with pytest.raises(HTTPException) as caught:
            await delete_bot(USER, "b-home")
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_no_hand_made_bot_in_home():
    home_workspace = {"workspace_id": HOME, "user_id": USER, "name": "Home"}
    body = BotCreate(workspace_id=HOME, name="Second")
    with patch(
        "src.server.app.bots._own_workspace", AsyncMock(return_value=home_workspace)
    ), patch("src.server.app.bots.is_home_id", return_value=True):
        with pytest.raises(HTTPException) as caught:
            await _create(USER, body)
    assert caught.value.status_code == 400


async def _create(user_id: str, body: BotCreate):
    from src.server.app.bots import create_bot

    return await create_bot(user_id, body)
