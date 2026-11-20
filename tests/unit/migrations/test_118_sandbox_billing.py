"""118 only adds billing columns and the reporter's queue index.

The previous release keeps serving against the migrated schema until the
swap, so the upgrade may not rewrite a column it reads. The columns are
nullable on purpose: an unresettled run has no timestamp and a retryable
failure carries no charge, while a settled run with nothing to bill carries
zero.
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
        "migration_118", _VERSIONS / "118_sandbox_billing.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events: list[str] = []
    op = MagicMock()
    op.execute.side_effect = lambda sql: events.append(" ".join(str(sql).split()))
    monkeypatch.setattr(module, "op", op)
    return module, events


def test_it_follows_117_in_a_linear_chain(migration):
    module, _events = migration
    assert (module.revision, module.down_revision) == ("118", "117")


def test_the_upgrade_adds_only_its_columns_and_index(migration):
    module, events = migration

    module.upgrade()

    assert events[0] == "SET lock_timeout = '5s'"
    assert events[1].startswith("ALTER TABLE computer_runs ADD COLUMN IF NOT EXISTS")
    for column in (
        "billing_reported_at TIMESTAMPTZ",
        "billing_credits BIGINT",
        "billing_error TEXT",
    ):
        assert column in events[1], column
    assert (
        "CREATE INDEX IF NOT EXISTS idx_computer_runs_billing_due"
        " ON computer_runs (provider_kind, ended_at)"
        " WHERE ended_at IS NOT NULL AND billing_reported_at IS NULL"
    ) == events[2]
    assert not any("CREATE TABLE" in e or "DROP" in e for e in events)


def test_the_downgrade_drops_only_what_it_added(migration):
    module, events = migration

    module.downgrade()

    assert "DROP INDEX IF EXISTS idx_computer_runs_billing_due" in events
    assert any("DROP COLUMN IF EXISTS billing_error" in e for e in events)
    assert not any("DROP TABLE" in e for e in events)
