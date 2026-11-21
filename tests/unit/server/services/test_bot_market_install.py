"""Installing a built-in Bot: a copy, with the workspace's own limits still on.

The interesting cases are the ones the UI can actually hit: the obvious name
is taken (suffix instead of failing), every candidate is taken (the caller
renames), and the workspace is at its cap (the caller picks another room).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.server.database import bots as bot_db
from src.server.models.bot_market import CatalogBot
from src.server.services.bot_market import install as install_module
from src.server.services.bot_market.install import (
    MAX_NAME_ATTEMPTS,
    NameTaken,
    WorkspaceFull,
    _candidates,
    install_bot,
)

TEMPLATE = CatalogBot.model_validate(
    {
        "slug": "example-bot",
        "name": "示例 Bot",
        "summary": "A summary.",
        "description": "Longer text.",
        "category": "research",
        "version": "1.2.3",
        "template": {
            "persona": "You are a researcher.",
            "model": None,
            "skills": ["company-profile"],
            "tools_allow": ["get_quote", "get_daily_prices"],
            "tools_deny": ["send_bot_message"],
            "approval": "ask",
            "memory_scopes": ["workspace"],
        },
    }
)

USER_ID = "user-1"
WORKSPACE_ID = "22222222-2222-4222-8222-222222222222"
BOT_ROW = {
    "bot_id": "11111111-1111-4111-8111-111111111111",
    "user_id": USER_ID,
    "workspace_id": WORKSPACE_ID,
    "name": "示例 Bot",
}


def test_candidates_suffix_within_the_name_limit():
    names = list(_candidates("A" * 80))
    assert names[0] == "A" * 64
    assert names[1] == "A" * 62 + " 2"
    assert all(len(name) <= 64 for name in names)
    assert len(names) == MAX_NAME_ATTEMPTS


def test_candidates_fall_back_to_a_name_when_asked_for_blank():
    assert list(_candidates("   "))[0] == "Bot"


@pytest.mark.asyncio
async def test_install_copies_the_template_and_records_where_it_came_from():
    with (
        patch.object(bot_db, "create_bot", AsyncMock(return_value=BOT_ROW)) as create,
        patch.object(
            install_module.market_db,
            "record_install",
            AsyncMock(return_value={"install_id": "i-1"}),
        ) as record,
    ):
        install, row = await install_bot(
            user_id=USER_ID, bot=TEMPLATE, workspace_id=WORKSPACE_ID
        )

    assert row is BOT_ROW
    assert install["install_id"] == "i-1"
    create.assert_awaited_once()
    kwargs = create.await_args
    assert kwargs.args[:3] == (USER_ID, WORKSPACE_ID, "示例 Bot")
    assert kwargs.kwargs["persona"] == "You are a researcher."
    assert kwargs.kwargs["skills"] == ["company-profile"]
    assert kwargs.kwargs["tools_allow"] == ["get_quote", "get_daily_prices"]
    assert kwargs.kwargs["tools_deny"] == ["send_bot_message"]
    assert kwargs.kwargs["model"] is None
    record.assert_awaited_once_with(
        user_id=USER_ID,
        slug="example-bot",
        version="1.2.3",
        workspace_id=WORKSPACE_ID,
        bot_id=BOT_ROW["bot_id"],
    )


@pytest.mark.asyncio
async def test_a_taken_name_gets_a_suffix_instead_of_failing():
    create = AsyncMock(
        side_effect=[bot_db.BotNameTaken("示例 Bot"), {**BOT_ROW, "name": "示例 Bot 2"}]
    )
    with (
        patch.object(bot_db, "create_bot", create),
        patch.object(
            install_module.market_db, "record_install", AsyncMock(return_value={"install_id": "i-1"})
        ),
    ):
        _install, row = await install_bot(
            user_id=USER_ID, bot=TEMPLATE, workspace_id=WORKSPACE_ID
        )

    assert row["name"] == "示例 Bot 2"
    assert [call.args[2] for call in create.await_args_list] == ["示例 Bot", "示例 Bot 2"]


@pytest.mark.asyncio
async def test_every_candidate_taken_asks_the_caller_to_rename():
    create = AsyncMock(side_effect=bot_db.BotNameTaken("taken"))
    with patch.object(bot_db, "create_bot", create):
        with pytest.raises(NameTaken):
            await install_bot(user_id=USER_ID, bot=TEMPLATE, workspace_id=WORKSPACE_ID)
    assert create.await_count == MAX_NAME_ATTEMPTS


@pytest.mark.asyncio
async def test_a_full_workspace_is_reported_as_such():
    create = AsyncMock(side_effect=ValueError("a workspace holds at most 20 bots"))
    with patch.object(bot_db, "create_bot", create):
        with pytest.raises(WorkspaceFull):
            await install_bot(user_id=USER_ID, bot=TEMPLATE, workspace_id=WORKSPACE_ID)


@pytest.mark.asyncio
async def test_the_caller_can_name_the_copy():
    create = AsyncMock(return_value={**BOT_ROW, "name": "我的研究员"})
    with (
        patch.object(bot_db, "create_bot", create),
        patch.object(
            install_module.market_db, "record_install", AsyncMock(return_value={"install_id": "i-1"})
        ),
    ):
        await install_bot(
            user_id=USER_ID,
            bot=TEMPLATE,
            workspace_id=WORKSPACE_ID,
            name="  我的研究员  ",
        )
    assert create.await_args.args[2] == "我的研究员"
