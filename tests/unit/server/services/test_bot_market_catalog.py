"""The shipped Bot catalogue: what the build may offer, and how it is validated.

These pin the shape of ``catalog.json`` rather than any one Bot, so adding or
removing a template is a data change while a malformed template is a test
failure. The API helpers (locale, card, detail) are pinned here too, since they
decide what a list response may contain.
"""

from __future__ import annotations

import pytest

import src.server.services.bot_market.catalog as catalog_module

from src.server.models.bot_market import BotMarketCatalog
from src.server.services.bot_market import (    card,
    load_catalog,
    category_label,
    category_options,
    detail,
    find_bot,
    resolve_locale,
)


def test_the_shipped_catalog_loads_and_is_well_formed():
    shipped = load_catalog()

    assert shipped.catalog_version
    assert shipped.categories
    assert len(shipped.bots) >= 3
    assert shipped.bots[0].slug
    for bot in shipped.bots:
        assert bot.template.tools_allow, bot.slug
        assert bot.template.persona, bot.slug
        assert bot.name.strip(), bot.slug
        assert bot.summary.strip(), bot.slug


def test_every_bot_names_a_shipped_category():
    known = {category.id for category in load_catalog().categories}
    for bot in load_catalog().bots:
        assert bot.category in known, bot.slug


def test_find_bot_is_exact_and_tolerates_surrounding_space():
    first = load_catalog().bots[0]
    assert find_bot(first.slug) == first
    assert find_bot(f"  {first.slug}  ") == first
    assert find_bot("not-a-shipped-bot") is None
    assert find_bot("") is None


def test_locale_comes_from_the_header_and_defaults_to_english():
    assert resolve_locale("zh-CN,zh;q=0.9,en;q=0.8") == "zh"
    assert resolve_locale("zh") == "zh"
    assert resolve_locale("en-US") == "en"
    assert resolve_locale(None) == "en"
    assert resolve_locale("") == "en"


def test_category_labels_follow_the_locale():
    category = load_catalog().categories[0]
    assert category_label(category.id, "zh") == category.label.zh
    assert category_label(category.id, "en") == category.label.en
    assert category_label("missing", "zh") == "missing"
    options = category_options("zh")
    assert [option.id for option in options] == [c.id for c in load_catalog().categories]
    assert all(option.label for option in options)


def test_a_card_has_no_persona_and_carries_the_installed_flag():
    bot = load_catalog().bots[0]
    summary = card(bot, installed=True)
    assert summary.slug == bot.slug
    assert summary.installed is True
    assert not hasattr(summary, "persona")
    assert summary.icon


def test_a_detail_carries_the_template_but_not_the_deny_list_secrets():
    bot = load_catalog().bots[0]
    shown = detail(bot, installs=[])
    assert shown.persona == bot.template.persona
    assert shown.tools == bot.template.tools_allow
    assert shown.skills == bot.template.skills
    assert shown.installs == []


def _raw_catalog(**overrides):
    """A minimal valid catalogue that a case can break one field at a time."""
    raw = {
        "catalog_version": "1.0.0",
        "categories": [{"id": "research", "label": {"zh": "研究", "en": "Research"}}],
        "bots": [
            {
                "slug": "example-bot",
                "name": "Example",
                "summary": "A summary.",
                "category": "research",
                "version": "1.0.0",
                "template": {"tools_allow": ["get_quote"]},
            }
        ],
    }
    raw.update(overrides)
    return raw


def test_an_empty_tool_allow_list_is_rejected():
    raw = _raw_catalog()
    raw["bots"][0]["template"]["tools_allow"] = []
    with pytest.raises(ValueError):
        BotMarketCatalog.model_validate(raw)


def test_an_unknown_template_key_is_rejected():
    raw = _raw_catalog()
    raw["bots"][0]["template"]["secrets"] = {"token": "nope"}
    with pytest.raises(ValueError):
        BotMarketCatalog.model_validate(raw)


def test_an_unknown_bot_category_is_rejected():
    raw = _raw_catalog()
    raw["bots"][0]["category"] = "not-a-category"
    with pytest.raises(ValueError):
        BotMarketCatalog.model_validate(raw)


def test_duplicate_slugs_are_rejected():
    raw = _raw_catalog()
    first = raw["bots"][0]
    raw["bots"] = [first, {**first, "name": "Another"}]
    with pytest.raises(ValueError):
        BotMarketCatalog.model_validate(raw)


def test_the_catalog_is_read_once_and_cached():
    catalog_module.load_catalog.cache_clear()
    first = catalog_module.load_catalog()
    second = catalog_module.load_catalog()
    assert first is second


def test_the_uzi_investor_roster_is_complete_and_role_play_only():
    """Every investor in UZI-Skill's panel is a Bot, and none claims to be them.

    The roster is derived data (see NOTICE); pinning the count catches a
    generator that silently drops the tail of the 66, and the persona checks
    keep the role-play boundary from being edited away.
    """
    investor_bots = [bot for bot in load_catalog().bots if bot.category == "investor"]

    assert len(investor_bots) == 66
    assert len({bot.slug for bot in investor_bots}) == 66
    for bot in investor_bots:
        assert bot.slug.startswith("uzi-"), bot.slug
        assert "不代表本人观点" in bot.template.persona, bot.slug
        assert "不构成买卖建议" in bot.template.persona, bot.slug
        assert bot.template.tools_allow, bot.slug
    buffett = next(bot for bot in investor_bots if bot.slug == "uzi-buffett")
    assert buffett.featured
    assert "Warren Buffett" in buffett.template.persona

