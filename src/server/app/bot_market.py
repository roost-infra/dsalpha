"""Built-in Bot market API.

The market sells (for now: gives away) the Bot templates this build ships.
There is no listing management endpoint and no publishing path: the catalogue
is code, and the only write a caller can make is an install. A template's
persona and tool lists are readable to every signed-in user, since v1 is free.

Endpoints:
- GET  /api/v1/market/bots               - The built-in templates
- GET  /api/v1/market/bots/{slug}        - One template, with where it is installed
- POST /api/v1/market/bots/{slug}/install - Copy it into a workspace
- GET  /api/v1/market/me/installs        - The caller's install journal
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from src.server.database import bot_market as market_db
from src.server.database.home_workspace import is_home_id
from src.server.database.workspace import get_workspace
from src.server.dependencies.principal import (
    ReadPrincipal,
    WorkspaceWritePrincipal,
    assert_reaches,
)
from src.server.models.bot_market import (
    MarketBotDetail,
    MarketBotList,
    MarketInstallList,
    MarketInstallLocation,
    MarketInstallRecord,
    MarketInstallRequest,
    MarketInstallResponse,
    MarketInstalledBot,
)
from src.server.services import bot_market as market
from src.server.utils.api import require_workspace_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market", tags=["Bot Market"])


def _locale(request: Request) -> str:
    return market.resolve_locale(request.headers.get("accept-language"))


@router.get("/bots", response_model=MarketBotList)
async def list_bots(
    request: Request,
    principal: ReadPrincipal,
    q: Optional[str] = Query(default=None, max_length=100),
    category: Optional[str] = Query(default=None, max_length=32),
) -> MarketBotList:
    """The built-in Bot templates, already installed ones flagged.

    Search reads the card text (name, summary, tags), never the persona: a list
    response must not ship 20 KB of prompt per Bot.
    """
    installed = await market_db.installed_slugs(principal.user_id)
    query = (q or "").strip().lower()
    bots = []
    for bot in market.load_catalog().bots:
        if category and bot.category != category:
            continue
        if query:
            haystack = " ".join([bot.name, bot.summary, *bot.tags]).lower()
            if query not in haystack:
                continue
        bots.append(market.card(bot, installed=bot.slug in installed))
    bots.sort(key=lambda card: (not card.featured,))
    return MarketBotList(bots=bots, categories=market.category_options(_locale(request)))


@router.get("/bots/{slug}", response_model=MarketBotDetail)
async def get_bot(
    request: Request, principal: ReadPrincipal, slug: str
) -> MarketBotDetail:
    """One template with its persona, tools and the caller's install locations."""
    bot = market.find_bot(slug)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot template not found")
    rows = await market_db.installs_for_slug(principal.user_id, bot.slug)
    return market.detail(
        bot,
        installs=[MarketInstallLocation(**row) for row in rows],
    )


@router.post(
    "/bots/{slug}/install",
    response_model=MarketInstallResponse,
    status_code=201,
)
async def install_bot(
    principal: WorkspaceWritePrincipal,
    slug: str,
    body: MarketInstallRequest,
) -> MarketInstallResponse:
    """Copy the template into a workspace the caller owns.

    The workspace's own rules still apply (20 Bots, unique names, not Home);
    the install adds a name suffix when the obvious one is taken.
    """
    bot = market.find_bot(slug)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot template not found")
    workspace_id = str(body.workspace_id)
    workspace = await get_workspace(workspace_id)
    require_workspace_owner(workspace, user_id=principal.user_id)
    assert workspace is not None
    await assert_reaches(principal, workspace_id=str(workspace["workspace_id"]))
    if is_home_id(principal.user_id, workspace["workspace_id"]):
        raise HTTPException(
            status_code=400,
            detail="Home holds the Chief of Staff; install into a workspace.",
        )
    if bot.template.model:
        from src.server.services.llm.thread_model import require_selectable_model

        await require_selectable_model(principal.user_id, bot.template.model)
    try:
        install, row = await market.install_bot(
            user_id=principal.user_id,
            bot=bot,
            workspace_id=str(workspace["workspace_id"]),
            name=body.name,
        )
    except market.WorkspaceFull as exc:
        raise HTTPException(
            status_code=409,
            detail=f"This workspace cannot hold another Bot: {exc}",
        ) from None
    except market.NameTaken:
        raise HTTPException(
            status_code=409,
            detail="A Bot with that name already exists in this workspace; pick another name.",
        ) from None
    except market.TemplateNotFound:
        raise HTTPException(status_code=404, detail="Bot template not found") from None
    return MarketInstallResponse(
        install_id=str(install.get("install_id") or ""),
        bot=MarketInstalledBot(
            bot_id=str(row["bot_id"]),
            name=str(row["name"]),
            workspace_id=str(row["workspace_id"]),
        ),
    )


@router.get("/me/installs", response_model=MarketInstallList)
async def my_installs(principal: ReadPrincipal) -> MarketInstallList:
    """Everything this user installed from the built-in market, newest first.

    The template's current name is resolved from the catalogue, not stored in
    the journal: a template renamed in a later build then reads under the name
    the rest of the market shows. A template removed from the build falls back
    to its slug, which is still what the install row is about.
    """
    rows = await market_db.list_installs(principal.user_id)
    installs = []
    for row in rows:
        template = market.find_bot(str(row.get("slug") or ""))
        installs.append(
            MarketInstallRecord(
                **{**row, "name": template.name if template else str(row.get("slug") or "")}
            )
        )
    return MarketInstallList(installs=installs)
