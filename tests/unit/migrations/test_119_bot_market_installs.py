"""119 only adds the built-in Bot market's install journal.

The catalogue itself is code, so no listing tables are created here. The
install row is append-only and points at the Bot and workspace it produced;
the downgrade drops the journal but must not touch the Bot rows it named.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "versions"


@pytest.fixture
def migration(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "migration_119", _VERSIONS / "119_bot_market_installs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events: list[str] = []
    op = MagicMock()
    op.execute.side_effect = lambda sql: events.append(" ".join(str(sql).split()))
    monkeypatch.setattr(module, "op", op)
    return module, events


def test_it_follows_118_in_a_linear_chain(migration):
    module, _events = migration
    assert (module.revision, module.down_revision) == ("119", "118")


def test_the_upgrade_creates_the_install_journal_and_its_indexes(migration):
    module, events = migration

    module.upgrade()

    assert events[0] == "SET lock_timeout = '5s'"
    created = events[1]
    assert "CREATE TABLE IF NOT EXISTS bot_market_installs" in created
    for column in (
        "install_id UUID PRIMARY KEY",
        "user_id VARCHAR(255) NOT NULL",
        "listing_slug TEXT NOT NULL",
        "listing_version TEXT NOT NULL",
        "workspace_id UUID NOT NULL",
        "bot_id UUID NOT NULL",
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    ):
        assert column in created, column
    assert "ON DELETE CASCADE" in created
    assert any("ix_bot_market_installs_buyer" in event for event in events)
    assert any("ix_bot_market_installs_slug" in event for event in events)
    assert not any("market_listings" in event or "market_versions" in event for event in events)


def test_the_downgrade_drops_its_table_and_indexes_only(migration):
    module, events = migration

    module.downgrade()

    assert "DROP INDEX IF EXISTS ix_bot_market_installs_slug" in events
    assert "DROP INDEX IF EXISTS ix_bot_market_installs_buyer" in events
    assert "DROP TABLE IF EXISTS bot_market_installs" in events
    assert not any("bots" in event and "DROP" in event for event in events)
