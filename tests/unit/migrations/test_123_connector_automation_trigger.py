"""123 admits connector automations into the trigger_type constraint."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "versions"


@pytest.fixture
def migration(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "migration_123", _VERSIONS / "123_connector_automation_trigger.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events: list[str] = []
    op = MagicMock()
    op.execute.side_effect = lambda sql: events.append(" ".join(str(sql).split()))
    monkeypatch.setattr(module, "op", op)
    return module, events


def test_it_follows_122(migration):
    module, _events = migration
    assert (module.revision, module.down_revision) == ("123", "122")


def test_the_upgrade_widens_the_check(migration):
    module, events = migration

    module.upgrade()

    assert any("DROP CONSTRAINT IF EXISTS automations_trigger_type_check" in event for event in events)
    assert any("'connector'" in event and "CHECK" in event for event in events)


def test_the_downgrade_removes_connector_rows_before_the_old_check(migration):
    module, events = migration

    module.downgrade()

    assert "DELETE FROM automations WHERE trigger_type = 'connector'" in events
    assert any("CHECK (trigger_type IN ('cron', 'once', 'price'))" in event for event in events)
