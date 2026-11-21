"""121 adds one JSON grant map to the bot row; nothing else moves."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "versions"


@pytest.fixture
def migration(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "migration_121", _VERSIONS / "121_bot_connector_grants.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events: list[str] = []
    op = MagicMock()
    op.execute.side_effect = lambda sql: events.append(" ".join(str(sql).split()))
    monkeypatch.setattr(module, "op", op)
    return module, events


def test_it_follows_120(migration):
    module, _events = migration
    assert (module.revision, module.down_revision) == ("121", "120")


def test_the_upgrade_adds_only_the_grant_map(migration):
    module, events = migration

    module.upgrade()

    assert events[0] == "SET lock_timeout = '5s'"
    assert (
        "ALTER TABLE bots ADD COLUMN IF NOT EXISTS connector_tools "
        "JSONB NOT NULL DEFAULT '{}'::jsonb" == events[1]
    )
    assert not any("CREATE TABLE" in event for event in events)


def test_the_downgrade_drops_only_that_column(migration):
    module, events = migration

    module.downgrade()

    assert "ALTER TABLE bots DROP COLUMN IF EXISTS connector_tools" in events
