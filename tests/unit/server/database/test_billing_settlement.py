"""The settlement queue's SQL guards.

Each statement here decides money: whether a run is still owed a settlement,
which usage row it settles from, and whether it leaves the queue. The guards
that matter are the ones a query executes without them: the queue predicate,
the settled guard that keeps a replay from restamping, and the task-row
exclusion that keeps a subagent's usage from being billed twice.

SQL is asserted by substring against the mocked cursor — the house pattern for
this layer; whole-query equality is whitespace-brittle.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from src.server.database.runs import billing_settlement as db

RUN_ID = "22222222-2222-2222-2222-222222222222"
POOL = "src.server.database.pool.get_db_connection"


def _pool_of(connection):
    @asynccontextmanager
    async def _fake():
        yield connection

    return patch(POOL, new=_fake)


def _sql(cursor):
    return cursor.execute.call_args_list[-1][0][0]


def _params(cursor):
    return cursor.execute.call_args_list[-1][0][1]


@pytest.mark.asyncio
async def test_marking_pending_keeps_the_first_clock_and_skips_settled_rows(
    mock_connection, mock_cursor
):
    mock_cursor.rowcount = 1
    with _pool_of(mock_connection):
        assert await db.mark_settle_pending(RUN_ID, "in_flight unreadable") is True

    sql = _sql(mock_cursor)
    assert "billing_settle_pending = TRUE" in sql
    # The FIRST time the figure was lost is the run's queue age; a retry must
    # not reset it.
    assert "COALESCE(" in sql
    assert "billing_settle_pending_at" in sql
    # A replay of the same teardown must not reopen a settled run.
    assert "billing_settled_at IS NULL" in sql
    assert _params(mock_cursor) == ("in_flight unreadable", RUN_ID)


@pytest.mark.asyncio
async def test_marking_pending_reports_a_run_it_could_not_flag(mock_connection, mock_cursor):
    mock_cursor.rowcount = 0
    with _pool_of(mock_connection):
        assert await db.mark_settle_pending(RUN_ID, "x") is False


@pytest.mark.asyncio
async def test_marking_settled_stamps_and_clears_the_queue(mock_connection, mock_cursor):
    mock_cursor.rowcount = 1
    with _pool_of(mock_connection):
        assert await db.mark_settled(RUN_ID, charged_credits=9, detail="released") is True

    sql = _sql(mock_cursor)
    assert "billing_settled_at = NOW()" in sql
    assert "billing_settle_pending = FALSE" in sql
    # The console's charge is the only priced figure; None must leave the old
    # value alone rather than write a zero it never confirmed.
    assert "COALESCE(%s, billing_charged_credits)" in sql
    assert "billing_settled_at IS NULL" in sql
    assert _params(mock_cursor) == (9, "released", RUN_ID)


@pytest.mark.asyncio
async def test_the_queue_reads_only_due_runs_with_a_real_usage_row(
    mock_connection, mock_cursor
):
    mock_cursor.fetchall.return_value = []
    with _pool_of(mock_connection):
        rows = await db.list_settle_pending(limit=5, grace_seconds=30)

    sql = _sql(mock_cursor)
    assert rows == []
    assert "JOIN LATERAL" in sql
    # A subagent's usage row is charged on its own path; settling from it would
    # charge the same tokens twice.
    assert "msg_type <> 'task'" in sql
    assert "billing_settle_pending" in sql
    assert "billing_settled_at IS NULL" in sql
    # The grace waits out the finalize transaction that writes the usage row.
    assert "make_interval(secs => %s)" in sql
    assert "LIMIT %s" in sql
    assert _params(mock_cursor) == (30, 5)


@pytest.mark.asyncio
async def test_the_queue_returns_dict_rows(mock_connection, mock_cursor):
    mock_cursor.fetchall.return_value = [
        {"run_id": RUN_ID, "token_usage": {"platform_cost": 0.1}, "is_byok": False}
    ]
    with _pool_of(mock_connection):
        rows = await db.list_settle_pending()
    assert rows[0]["run_id"] == RUN_ID


@pytest.mark.asyncio
async def test_the_counts_use_the_same_queue_predicate(mock_connection, mock_cursor):
    mock_cursor.fetchone.return_value = (3,)
    with _pool_of(mock_connection):
        assert await db.count_settle_pending(grace_seconds=10) == 3
    assert "COUNT(*)" in _sql(mock_cursor)
    assert "billing_settle_pending" in _sql(mock_cursor)

    mock_cursor.fetchone.return_value = (2,)
    with _pool_of(mock_connection):
        assert await db.count_pending_without_usage() == 2
    orphan_sql = _sql(mock_cursor)
    assert "NOT EXISTS" in orphan_sql
    assert "msg_type <> 'task'" in orphan_sql


@pytest.mark.asyncio
async def test_a_count_with_no_row_reads_as_zero(mock_connection, mock_cursor):
    mock_cursor.fetchone.return_value = None
    with _pool_of(mock_connection):
        assert await db.count_settle_pending() == 0
