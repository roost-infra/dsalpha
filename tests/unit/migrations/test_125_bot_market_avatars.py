"""125 backfills the emoji the market card already showed."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "versions"


@pytest.fixture
def migration(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "migration_125", _VERSIONS / "125_bot_market_avatars.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events: list[str] = []
    op = MagicMock()
    op.execute.side_effect = lambda sql: events.append(" ".join(str(sql).split()))
    monkeypatch.setattr(module, "op", op)
    return module, events


def test_it_follows_124(migration):
    module, _events = migration
    assert (module.revision, module.down_revision) == ("125", "124")


def test_the_upgrade_sets_emoji_only_where_the_avatar_is_empty(migration):
    module, events = migration

    module.upgrade()

    update = next(event for event in events if "UPDATE bots" in event)
    assert "jsonb_build_object('kind', 'emoji', 'emoji', v.icon)" in update
    assert "i.listing_slug = v.slug" in update
    assert "b.avatar IS NULL OR b.avatar = '{}'::jsonb" in update
    assert "('uzi-buffett', '🏛️')" in module._CATALOG_ICONS


def test_the_downgrade_keeps_a_readers_own_avatar(migration):
    module, events = migration

    module.downgrade()

    assert not any("UPDATE bots" in event or "DELETE" in event for event in events)
