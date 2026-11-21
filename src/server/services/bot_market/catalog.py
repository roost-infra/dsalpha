"""Load the built-in Bot catalogue shipped with the build.

The platform's Bot templates are code, like the plugins under ``plugins/``:
adding one is a commit, and every deployment of that build offers the same
set. The catalogue is validated when first read, so a malformed entry fails
at startup rather than at the first install, and the JSON stays the single
place a template is edited.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Optional

from src.server.models.bot_market import (
    BotMarketCatalog,
    CatalogBot,
    MarketBotCard,
    MarketBotDetail,
    MarketCategory,
    MarketInstallLocation,
)

CATALOG_FILE = "catalog.json"


@lru_cache(maxsize=1)
def load_catalog() -> BotMarketCatalog:
    """The shipped catalogue, validated and cached for the life of the process."""
    raw = files(__package__).joinpath(CATALOG_FILE).read_text(encoding="utf-8")
    return BotMarketCatalog.model_validate(json.loads(raw))


def find_bot(slug: str) -> Optional[CatalogBot]:
    """The built-in template under *slug*, or None when the build has no such bot."""
    wanted = (slug or "").strip()
    if not wanted:
        return None
    for bot in load_catalog().bots:
        if bot.slug == wanted:
            return bot
    return None


def resolve_locale(accept_language: Optional[str]) -> str:
    """``zh`` or ``en`` from an ``Accept-Language`` header.

    Only the shipped display names are localized; Bot content (names, personas)
    is authored once and left alone. A missing or unrecognised header gets
    English, which is also the fallback the rest of the API uses.
    """
    language = (accept_language or "").strip().lower()
    return "zh" if language.startswith("zh") else "en"


def category_label(category_id: str, locale: str) -> str:
    """One category's display name in *locale*, falling back to English."""
    for category in load_catalog().categories:
        if category.id == category_id:
            return category.label.zh if locale == "zh" else category.label.en
    return category_id


def category_options(locale: str) -> list[MarketCategory]:
    """The filter chips the market page draws, in catalogue order."""
    return [
        MarketCategory(id=category.id, label=category_label(category.id, locale))
        for category in load_catalog().categories
    ]


def card(bot: CatalogBot, *, installed: bool) -> MarketBotCard:
    """The grid card for one template. Nothing persona-sized leaks into a list."""
    return MarketBotCard(
        slug=bot.slug,
        name=bot.name,
        summary=bot.summary,
        category=bot.category,
        tags=list(bot.tags),
        icon=bot.icon,
        version=bot.version,
        featured=bot.featured,
        installed=installed,
    )


def detail(
    bot: CatalogBot,
    *,
    installs: list[MarketInstallLocation],
) -> MarketBotDetail:
    """The detail page's payload. The market is free, so the persona is public."""
    return MarketBotDetail(
        slug=bot.slug,
        name=bot.name,
        summary=bot.summary,
        description=bot.description,
        category=bot.category,
        tags=list(bot.tags),
        icon=bot.icon,
        version=bot.version,
        featured=bot.featured,
        persona=bot.template.persona,
        tools=list(bot.template.tools_allow),
        skills=list(bot.template.skills),
        installs=installs,
    )
