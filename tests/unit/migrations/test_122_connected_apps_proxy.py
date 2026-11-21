"""122 adds the hash the managed MCP proxy looks an installation up by."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "versions"


@pytest.fixture
def migration(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "migration_122", _VERSIONS / "122_connected_apps_proxy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events: list[str] = []
    op = MagicMock()
    op.execute.side_effect = lambda sql: events.append(" ".join(str(sql).split()))
    monkeypatch.setattr(module, "op", op)
    return module, events


def test_it_follows_121(migration):
    module, _events = migration
    assert (module.revision, module.down_revision) == ("122", "121")


def test_the_upgrade_adds_only_the_hash_and_its_index(migration):
    module, events = migration

    module.upgrade()

    assert (
        "ALTER TABLE connected_app_installations ADD COLUMN IF NOT EXISTS "
        "proxy_token_hash TEXT" in events
    )
    assert any("CREATE INDEX IF NOT EXISTS ix_connected_app_installations_proxy" in event for event in events)


def test_the_downgrade_drops_its_objects(migration):
    module, events = migration

    module.downgrade()

    assert "DROP INDEX IF EXISTS ix_connected_app_installations_proxy" in events
    assert (
        "ALTER TABLE connected_app_installations DROP COLUMN IF EXISTS proxy_token_hash"
        in events
    )
