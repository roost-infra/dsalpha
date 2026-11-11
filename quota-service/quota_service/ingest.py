"""Usage ingestion: book token/tool/sandbox spend into the ledger.

Runs on a timer inside the service process. Two sources, each idempotent via
the ledger's ``(source, source_id)`` unique key:

* ``public.conversation_usages`` — dsalpha has already priced the turn
  (platform-key tokens plus per-tool infrastructure credits). We only book.
* ``public.computer_runs`` — running intervals of metered machines. Priced
  here from the user's plan ``sandbox_pricing``, in whole-second increments.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from psycopg import AsyncCursor

from .config import Settings
from .credits import add_credits, grant_month
from .db import pool
from .quota import Plan, plan_from_row

logger = logging.getLogger(__name__)

METERED_KINDS = ("daytona", "docker", "e2b")
_INGEST_LOCK = 4821001  # advisory lock: one ingester across replicas
_CONV_CURSOR = "conversation_usages"
_PAGE = 1000


class IngestStats:
    def __init__(self) -> None:
        self.ledger_entries = 0
        self.errors = 0
        self.last_success = 0.0
        self.last_skip = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "ledger_entries": self.ledger_entries,
            "errors": self.errors,
            "last_success": self.last_success,
            "last_skip": self.last_skip,
        }


stats = IngestStats()


def sandbox_credits(seconds: float, credits_per_hour: float) -> float:
    """Whole-second sandbox spend; 0 for a non-positive rate."""
    if seconds <= 0 or credits_per_hour <= 0:
        return 0.0
    return round(float(seconds) / 3600.0 * float(credits_per_hour), 6)


def price_for_tier(plan: Plan, tier: str, fallback: float) -> float:
    """The plan's per-hour price for a tier, else its default, else the deployment's."""
    pricing = plan.sandbox_pricing or {}
    value = pricing.get(tier)
    if value is None:
        value = pricing.get("default")
    try:
        return float(value) if value is not None else float(fallback)
    except (TypeError, ValueError):
        return float(fallback)


# ---------------------------------------------------------------------------
# State cursor (one row per source in billing.ingest_state)
# ---------------------------------------------------------------------------


async def _get_state(cur: AsyncCursor, name: str) -> Optional[str]:
    await cur.execute("SELECT cursor FROM billing.ingest_state WHERE name = %s", (name,))
    row = await cur.fetchone()
    return str(row["cursor"]) if row and row["cursor"] else None


async def _set_state(cur: AsyncCursor, name: str, value: str) -> None:
    await cur.execute(
        "INSERT INTO billing.ingest_state (name, cursor, updated_at) "
        "VALUES (%s, %s, now()) "
        "ON CONFLICT (name) DO UPDATE SET cursor = EXCLUDED.cursor, updated_at = now()",
        (name, value),
    )


# ---------------------------------------------------------------------------
# conversation_usages -> token / tool ledger entries
# ---------------------------------------------------------------------------


async def ingest_conversation_usages(cur: AsyncCursor, settings: Settings) -> int:
    cursor = await _get_state(cur, _CONV_CURSOR)
    if cursor:
        after_ts, _, after_id = cursor.partition("|")
    else:
        after_ts = "1970-01-01T00:00:00+00:00"
        after_id = "00000000-0000-0000-0000-000000000000"

    await cur.execute(
        """
        SELECT conversation_usage_id, user_id, token_credits,
               infrastructure_credits, credit_exempt, created_at
        FROM public.conversation_usages
        WHERE status IN ('completed', 'interrupted', 'error', 'cancelled')
          AND (created_at > %s::timestamptz
               OR (created_at = %s::timestamptz
                   AND conversation_usage_id > %s::uuid))
        ORDER BY created_at, conversation_usage_id
        LIMIT %s
        """,
        (after_ts, after_ts, after_id, _PAGE),
    )
    rows = await cur.fetchall()
    for row in rows:
        if row["credit_exempt"]:
            continue
        usage_id = str(row["conversation_usage_id"])
        token = float(row["token_credits"] or 0)
        infra = float(row["infrastructure_credits"] or 0)
        if token > 0:
            await add_credits(
                cur,
                user_id=row["user_id"],
                delta=-token,
                reason="token",
                source="conversation_usage",
                source_id=f"{usage_id}:token",
            )
        if infra > 0:
            await add_credits(
                cur,
                user_id=row["user_id"],
                delta=-infra,
                reason="tool",
                source="conversation_usage",
                source_id=f"{usage_id}:tool",
            )

    if rows:
        last = rows[-1]
        created = last["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        await _set_state(
            cur,
            _CONV_CURSOR,
            f"{created.isoformat()}|{last['conversation_usage_id']}",
        )
    return len(rows)


# ---------------------------------------------------------------------------
# computer_runs -> sandbox ledger entries
# ---------------------------------------------------------------------------


async def ingest_sandbox_runs(cur: AsyncCursor, settings: Settings) -> int:
    await cur.execute(
        """
        SELECT r.run_id, r.user_id, r.provider_kind, r.resource_tier,
               r.started_at, r.ended_at, b.billed_until
        FROM public.computer_runs r
        LEFT JOIN billing.run_billing b ON b.run_id = r.run_id
        WHERE r.provider_kind = ANY(%s)
          AND r.started_at < now()
          AND COALESCE(r.ended_at, now())
              > COALESCE(b.billed_until, r.started_at)
        ORDER BY r.started_at
        LIMIT %s
        """,
        (list(METERED_KINDS), _PAGE),
    )
    runs = await cur.fetchall()
    if not runs:
        return 0

    plans: dict[str, Plan] = {}
    booked = 0
    now = datetime.now(timezone.utc)
    for run in runs:
        user_id = run["user_id"]
        plan = plans.get(user_id)
        if plan is None:
            await cur.execute(
                "SELECT p.* FROM billing.user_plans up "
                "JOIN billing.plans p ON p.code = up.plan_code "
                "WHERE up.user_id = %s",
                (user_id,),
            )
            row = await cur.fetchone()
            if row is None:
                await cur.execute(
                    "SELECT * FROM billing.plans WHERE code = %s",
                    (settings.default_plan,),
                )
                row = await cur.fetchone()
            if row is None:
                continue
            plan = plan_from_row(row)
            plans[user_id] = plan

        price = price_for_tier(plan, run["resource_tier"], settings.sandbox_default_per_hour)
        if price <= 0:
            continue

        start = run["billed_until"] or run["started_at"]
        end = run["ended_at"] or now
        end = min(end, now).replace(microsecond=0)
        if end <= start:
            continue

        credits = sandbox_credits((end - start).total_seconds(), price)
        if credits <= 0:
            continue

        source_id = f"{run['run_id']}:{int(end.timestamp())}"
        inserted = await add_credits(
            cur,
            user_id=user_id,
            delta=-credits,
            reason="sandbox",
            source="computer_run",
            source_id=source_id,
        )
        if not inserted:
            continue  # already billed to this second
        await cur.execute(
            """
            INSERT INTO billing.run_billing (run_id, user_id, billed_until, credits_billed)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET
                billed_until = GREATEST(
                    billing.run_billing.billed_until, EXCLUDED.billed_until
                ),
                credits_billed = billing.run_billing.credits_billed
                                 + EXCLUDED.credits_billed
            """,
            (run["run_id"], user_id, end, credits),
        )
        booked += 1
    return booked


# ---------------------------------------------------------------------------
# Monthly grants
# ---------------------------------------------------------------------------


async def assign_default_plans(cur: AsyncCursor, settings: Settings) -> int:
    """Give every user without a plan the deployment's current default.

    During a free-trial month the default is the trial plan; after launch it is
    free, so a new signup still has a row to grant against. ON CONFLICT makes
    this safe to run every pass.
    """
    await cur.execute(
        """
        INSERT INTO billing.user_plans (user_id, plan_code, assigned_by, note)
        SELECT u.user_id, %s, 'system', 'default plan auto-assignment'
        FROM public.users u
        LEFT JOIN billing.user_plans up ON up.user_id = u.user_id
        WHERE up.user_id IS NULL
        ON CONFLICT (user_id) DO NOTHING
        """,
        (settings.default_plan,),
    )
    return cur.rowcount


async def maybe_grant_monthly(cur: AsyncCursor, settings: Settings) -> int:
    """Grant each assigned plan's monthly credits once per user per month.

    The grant is idempotent on ``(source='grant', source_id=user:month)``, so a
    user assigned mid-month gets this month's credits on the next pass. The
    query runs every pass rather than short-circuiting on one global cursor:
    signups and trial-plan moves arrive between passes.
    """
    await cur.execute(
        "SELECT up.user_id, p.monthly_credits "
        "FROM billing.user_plans up "
        "JOIN billing.plans p ON p.code = up.plan_code "
        "WHERE p.monthly_credits > 0"
    )
    granted = 0
    for row in await cur.fetchall():
        if await grant_month(
            cur,
            user_id=row["user_id"],
            credits=float(row["monthly_credits"]),
            tz=settings.monthly_grant_tz,
        ):
            granted += 1
    return granted


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


async def run_once(settings: Settings) -> dict[str, Any]:
    """One ingestion pass, under an advisory lock so replicas never double-book."""
    if not settings.ingest_enabled:
        return {"skipped": "disabled"}

    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT pg_try_advisory_xact_lock(%s) AS locked", (_INGEST_LOCK,)
                )
                row = await cur.fetchone()
                if not row or not row["locked"]:
                    stats.last_skip = "lock busy"
                    return {"skipped": "lock busy"}

                assigned = await assign_default_plans(cur, settings)
                conversations = await ingest_conversation_usages(cur, settings)
                sandboxes = await ingest_sandbox_runs(cur, settings)
                grants = await maybe_grant_monthly(cur, settings)

    stats.ledger_entries += conversations + sandboxes
    stats.last_success = time.time()
    stats.last_skip = ""
    return {
        "assigned": assigned,
        "conversations": conversations,
        "sandboxes": sandboxes,
        "grants": grants,
    }


async def run_forever(settings: Settings) -> None:
    logger.info(
        "usage ingestion started (interval=%ss)", settings.ingest_interval_seconds
    )
    while True:
        try:
            result = await run_once(settings)
            if result.get("skipped") != "disabled":
                logger.debug("ingest pass: %s", result)
        except asyncio.CancelledError:
            logger.info("usage ingestion stopped")
            raise
        except Exception:  # noqa: BLE001 - a bad pass must not kill the loop
            stats.errors += 1
            logger.exception("usage ingestion pass failed")
        await asyncio.sleep(settings.ingest_interval_seconds)
