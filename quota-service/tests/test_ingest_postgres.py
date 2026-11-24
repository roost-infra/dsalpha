"""Postgres regressions. Set QUOTA_TEST_POSTGRES to a disposable local server."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from quota_service import ingest
from quota_service.config import Settings


@pytest.fixture
def dsn():
    server = os.environ.get("QUOTA_TEST_POSTGRES")
    if not server:
        pytest.skip("QUOTA_TEST_POSTGRES is not configured")
    name = f"quota_test_{uuid4().hex}"
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        test_dsn = make_conninfo(server, dbname=name)
        try:
            with psycopg.connect(test_dsn) as conn:
                schema = Path(ingest.__file__).with_name("schema.sql").read_text(encoding="utf-8")
                conn.execute(schema)
                conn.execute("""
                    CREATE TABLE conversation_usages (
                        conversation_usage_id uuid PRIMARY KEY,
                        user_id text NOT NULL,
                        token_credits numeric NOT NULL DEFAULT 1,
                        infrastructure_credits numeric NOT NULL DEFAULT 0,
                        credit_exempt boolean NOT NULL DEFAULT false,
                        status text NOT NULL DEFAULT 'completed',
                        created_at timestamptz NOT NULL DEFAULT now(),
                        quota_ingest_xid xid8 DEFAULT pg_current_xact_id()
                    );
                    CREATE TABLE computer_runs (
                        run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id text NOT NULL,
                        provider_kind text NOT NULL DEFAULT 'docker',
                        resource_tier text NOT NULL DEFAULT 'standard',
                        started_at timestamptz NOT NULL,
                        ended_at timestamptz
                    );
                """)
            yield test_dsn
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def _run(coroutine):
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def test_conversation_ingest_covers_reversed_commits_and_pagination(dsn, monkeypatch):
    monkeypatch.setattr(ingest, "_PAGE", 1)

    async def scenario():
        settings = Settings(dsn, "fixture-token", "fixture-admin")
        async with (
            await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as ingester,
            await psycopg.AsyncConnection.connect(dsn) as slow,
            await psycopg.AsyncConnection.connect(dsn) as fast,
        ):
            await slow.execute(
                "INSERT INTO conversation_usages VALUES (gen_random_uuid(), 'slow')"
            )
            await fast.execute(
                "INSERT INTO conversation_usages VALUES (gen_random_uuid(), 'fast-first'), "
                "(gen_random_uuid(), 'fast-second')"
            )
            await fast.commit()

            async def collect():
                async with ingester.transaction(), ingester.cursor() as cur:
                    return await ingest.ingest_conversation_usages(cur, settings)

            assert await collect() == 0
            await slow.commit()
            assert await collect() == 1
            assert await collect() == 1
            assert await collect() == 1
            assert await collect() == 0
            cur = await ingester.execute("SELECT user_id, delta FROM billing.ledger")
            assert {row["user_id"]: row["delta"] for row in await cur.fetchall()} == {
                "slow": -1, "fast-first": -1, "fast-second": -1,
            }

    _run(scenario())


def test_sandbox_ingest_rotates_active_and_unpriced_runs(dsn, monkeypatch):
    monkeypatch.setattr(ingest, "_PAGE", 2)

    async def scenario():
        settings = Settings(dsn, "fixture-token", "fixture-admin", sandbox_default_per_hour=0)
        async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO computer_runs (user_id, resource_tier, started_at)
                    VALUES ('unpriced', 'unknown', now() - interval '1 hour'),
                           ('active', 'standard', now() - interval '30 min'),
                           ('new', 'standard', now() - interval '5 min');
                    WITH tail AS (
                        INSERT INTO computer_runs (user_id, started_at, ended_at)
                        VALUES ('tail', now() - interval '2 hours',
                                date_trunc('second', now() - interval '1 hour')
                                + interval '0.1 second')
                        RETURNING run_id, user_id, ended_at
                    )
                    INSERT INTO billing.run_billing (run_id, user_id, billed_until)
                    SELECT run_id, user_id, date_trunc('second', ended_at) FROM tail;
                """)

            async def collect():
                async with conn.transaction(), conn.cursor() as cur:
                    return await ingest.ingest_sandbox_runs(cur, settings)

            assert await collect() == 1
            # Make the old active run billable again, without sleeping.
            async with conn.transaction():
                await conn.execute("""
                    UPDATE billing.run_billing SET billed_until = billed_until - interval '1 s'
                    WHERE user_id = 'active'
                """)
            await collect()
            cur = await conn.execute("SELECT DISTINCT user_id FROM billing.ledger")
            assert {row["user_id"] for row in await cur.fetchall()} == {"active", "new"}

    _run(scenario())
