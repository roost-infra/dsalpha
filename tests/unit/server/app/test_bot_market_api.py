"""The Bot market's HTTP surface: filters, locale, and how limits read to a caller.

The catalogue is real here (the shipped one); only the DB reads are patched, so
these pin what a card and a detail actually carry and how a workspace refusal
maps to a status code.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.server.app import bot_market as api
from src.server.dependencies.principal import Principal
from src.server.models.bot_market import MarketInstallRequest
from src.server.services import bot_market as market

USER = "u-1"
PRINCIPAL = Principal(user_id=USER, auth="pat")
WS = "22222222-2222-4222-8222-222222222222"
BOT_ID = "11111111-1111-4111-8111-111111111111"
REQUEST_ZH = SimpleNamespace(headers={"accept-language": "zh-CN"})
REQUEST_EN = SimpleNamespace(headers={"accept-language": "en-US"})


@pytest.mark.asyncio
async def test_list_flags_installs_and_localizes_categories():
    with patch.object(api.market_db, "installed_slugs", AsyncMock(return_value={"earnings-analyst"})):
        answer = await api.list_bots(REQUEST_ZH, PRINCIPAL, q=None, category=None)

    assert answer.bots
    assert all(card.installed is (card.slug == "earnings-analyst") for card in answer.bots)
    assert answer.categories[0].label  # zh labels are filled
    # Featured cards sort first.
    flags = [card.featured for card in answer.bots]
    assert flags == sorted(flags, reverse=True)


@pytest.mark.asyncio
async def test_list_searches_card_text_and_filters_by_category():
    with patch.object(api.market_db, "installed_slugs", AsyncMock(return_value=set())):
        by_category = await api.list_bots(REQUEST_EN, PRINCIPAL, q=None, category="earnings")
        by_query = await api.list_bots(REQUEST_ZH, PRINCIPAL, q="财报", category=None)
        by_missing = await api.list_bots(REQUEST_EN, PRINCIPAL, q="zzz-nothing", category=None)

    assert [card.category for card in by_category.bots] == ["earnings"]
    assert by_query.bots and all("财报" in (card.name + card.summary + " ".join(card.tags)) for card in by_query.bots)
    assert by_missing.bots == []


@pytest.mark.asyncio
async def test_detail_carries_persona_and_the_callers_install_locations():
    rows = [
        {
            "install_id": "i-1",
            "workspace_id": WS,
            "workspace_name": "研究",
            "bot_id": BOT_ID,
            "bot_name": "A股研究员",
        }
    ]
    with patch.object(api.market_db, "installs_for_slug", AsyncMock(return_value=rows)):
        answer = await api.get_bot(REQUEST_ZH, PRINCIPAL, "a-share-researcher")

    assert answer.slug == "a-share-researcher"
    assert answer.persona
    assert answer.tools
    assert answer.skills
    assert answer.installs[0].workspace_name == "研究"


@pytest.mark.asyncio
async def test_an_unknown_slug_is_404():
    with pytest.raises(HTTPException) as caught:
        await api.get_bot(REQUEST_ZH, PRINCIPAL, "not-a-bot")
    assert caught.value.status_code == 404


async def _install(*, home: bool = False, service=None, workspace_exists: bool = True):
    workspace = {"workspace_id": WS, "user_id": USER} if workspace_exists else None

    def require_owner(found, *, user_id):
        if found is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

    with (
        patch.object(api, "get_workspace", AsyncMock(return_value=workspace)),
        patch.object(api, "require_workspace_owner", require_owner),
        patch.object(api, "assert_reaches", AsyncMock()),
        patch.object(api, "is_home_id", return_value=home),
        patch.object(
            api.market,
            "install_bot",
            service
            or AsyncMock(
                return_value=(
                    {"install_id": "i-1"},
                    {"bot_id": BOT_ID, "name": "A股研究员", "workspace_id": WS},
                )
            ),
        ),
    ):
        return await api.install_bot(
            PRINCIPAL, "a-share-researcher", MarketInstallRequest(workspace_id=WS)
        )


@pytest.mark.asyncio
async def test_install_returns_the_new_bot_and_its_journal_id():
    answer = await _install()
    assert answer.install_id == "i-1"
    assert answer.bot.bot_id == BOT_ID
    assert answer.bot.name == "A股研究员"


@pytest.mark.asyncio
async def test_install_refuses_home():
    with pytest.raises(HTTPException) as caught:
        await _install(home=True)
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_a_full_workspace_and_a_taken_name_read_as_conflicts():
    full = AsyncMock(side_effect=market.WorkspaceFull("a workspace holds at most 20 bots"))
    with pytest.raises(HTTPException) as full_error:
        await _install(service=full)
    assert full_error.value.status_code == 409

    taken = AsyncMock(side_effect=market.NameTaken("taken"))
    with pytest.raises(HTTPException) as taken_error:
        await _install(service=taken)
    assert taken_error.value.status_code == 409


@pytest.mark.asyncio
async def test_install_into_a_missing_workspace_is_404():
    with pytest.raises(HTTPException) as caught:
        await _install(workspace_exists=False)
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_my_installs_returns_the_journal_rows():
    rows = [
        {
            "install_id": "i-1",
            "slug": "a-share-researcher",
            "name": "A股研究员",
            "version": "1.0.0",
            "workspace_id": WS,
            "workspace_name": "研究",
            "bot_id": BOT_ID,
            "bot_name": "A股研究员",
            "created_at": "2026-11-21T00:00:00+00:00",
        }
    ]
    with patch.object(api.market_db, "list_installs", AsyncMock(return_value=rows)):
        answer = await api.my_installs(PRINCIPAL)
    assert [row.install_id for row in answer.installs] == ["i-1"]
    assert answer.installs[0].workspace_name == "研究"
