"""127 adds the settlement queue's columns and its partial index.

The previous release keeps serving against the migrated schema until the swap,
so the upgrade may only add columns: the new build writes them, the old one
never reads them. The queue flag is NOT NULL DEFAULT FALSE on purpose — a run
is settled unless something deliberately marks it otherwise, so the migration
touches no existing row's meaning.
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
        "migration_129", _VERSIONS / "129_billing_settle_pending.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events: list[str] = []
    op = MagicMock()
    op.execute.side_effect = lambda sql: events.append(" ".join(str(sql).split()))
    monkeypatch.setattr(module, "op", op)
    return module, events


def test_it_follows_126_in_a_linear_chain(migration):
    module, _events = migration
    assert (module.revision, module.down_revision) == ("129", "128")


def test_the_upgrade_adds_only_its_columns_and_index(migration):
    module, events = migration

    module.upgrade()

    assert events[0] == "SET lock_timeout = '5s'"
    assert events[1].startswith(
        "ALTER TABLE conversation_responses ADD COLUMN IF NOT EXISTS"
    )
    for column in (
        "billing_settle_pending BOOLEAN NOT NULL DEFAULT FALSE",
        "billing_settle_pending_at TIMESTAMPTZ",
        "billing_settle_error TEXT",
        "billing_settled_at TIMESTAMPTZ",
        "billing_charged_credits BIGINT",
    ):
        assert column in events[1], column
    assert (
        "CREATE INDEX IF NOT EXISTS idx_conversation_responses_settle_pending"
        " ON conversation_responses (billing_settle_pending_at)"
        " WHERE billing_settle_pending AND billing_settled_at IS NULL"
    ) == events[2]
    assert not any("CREATE TABLE" in e or "DROP" in e for e in events)


def test_the_downgrade_drops_only_what_it_added(migration):
    module, events = migration

    module.downgrade()

    assert "DROP INDEX IF EXISTS idx_conversation_responses_settle_pending" in events
    assert any(
        "DROP COLUMN IF EXISTS billing_settle_pending" in e for e in events
    )
    assert not any("DROP TABLE" in e for e in events)
