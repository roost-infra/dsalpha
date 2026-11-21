"""Migration 120: one row per account's Composio session.

The key never lands here — it lives in the vault — so the row only remembers
which Composio user and session belong to the account.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "versions"


@pytest.fixture
def migration(monkeypatch):
    spec = importlib.util.spec_from_file_location("migration_120", _VERSIONS / "120_connected_apps.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events: list[str] = []
    op = MagicMock()
    op.execute.side_effect = lambda sql: events.append(" ".join(str(sql).split()))
    monkeypatch.setattr(module, "op", op)
    return module, events


def test_it_follows_119_in_a_linear_chain(migration):
    module, _events = migration
    assert (module.revision, module.down_revision) == ("120", "119")


def test_the_upgrade_creates_the_installation_row(migration):
    module, events = migration

    module.upgrade()

    created = events[1]
    assert "CREATE TABLE IF NOT EXISTS connected_app_installations" in created
    for column in (
        "user_id VARCHAR(255) PRIMARY KEY",
        "composio_user_id VARCHAR(255) NOT NULL",
        "session_id VARCHAR(255) NOT NULL",
        "mcp_url TEXT NOT NULL",
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    ):
        assert column in created, column
    assert "ON DELETE CASCADE" in created
    assert any("ix_connected_app_installations_session" in event for event in events)


def test_the_downgrade_drops_only_its_own_objects(migration):
    module, events = migration

    module.downgrade()

    assert "DROP INDEX IF EXISTS ix_connected_app_installations_session" in events
    assert "DROP TABLE IF EXISTS connected_app_installations" in events
