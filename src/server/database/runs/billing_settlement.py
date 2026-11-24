"""The settlement queue's SQL: runs whose release could not be settled inline.

A run reaches this queue for one of two reasons, and both are money events:

* the release could not read a spend figure at teardown (the ``in_flight``
  read failed, or no row was there to read), so it deliberately did not retire
  the lease — retiring it with no figure releases the whole ceiling and gives
  the turn away;
* the release itself failed after its retries (5xx / network), so the lease
  will expire un-billed unless something settles it later.

The run's ``conversation_usages`` row is the durable figure that lets the
worker settle it. It is written by finalize *after* the gate tears down, so the
worker waits out a grace before reading and the join to it is the proof that
finalize committed: a pending run with no usage row yet is simply not due.

``billing_settle_pending`` is the queue flag and ``billing_settled_at`` the
terminal stamp; both are set here, in single guarded statements, so two
workers cannot settle the same run twice (the console's release is idempotent,
but the local record must not flap).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row

from src.server.database import pool

logger = logging.getLogger(__name__)

_ERROR_MAX = 500


def _error_text(message: Optional[str]) -> Optional[str]:
    if not message:
        return None
    return message[:_ERROR_MAX]


async def mark_settle_pending(run_id: str, reason: str) -> bool:
    """Flag a run whose release must be settled later. False when it is gone.

    Never overwrites an earlier pending clock: the first loss of a spend figure
    is the moment the run became un-settled, and preserving it keeps the
    queue's age honest across retries. A run already stamped settled (a replay
    of the same teardown) is left alone.
    """
    async with pool.get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE conversation_responses
                SET billing_settle_pending = TRUE,
                    billing_settle_pending_at = COALESCE(
                        billing_settle_pending_at, NOW()
                    ),
                    billing_settle_error = %s
                WHERE conversation_response_id = %s
                  AND billing_settled_at IS NULL
                """,
                (_error_text(reason), run_id),
            )
            return cur.rowcount == 1


async def mark_settle_error(run_id: str, message: str) -> None:
    """Record a retryable failure without dropping the run from the queue."""
    async with pool.get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE conversation_responses
                SET billing_settle_pending = TRUE,
                    billing_settle_pending_at = COALESCE(
                        billing_settle_pending_at, NOW()
                    ),
                    billing_settle_error = %s
                WHERE conversation_response_id = %s
                  AND billing_settled_at IS NULL
                """,
                (_error_text(message), run_id),
            )


async def mark_settled(
    run_id: str,
    *,
    charged_credits: Optional[int] = None,
    detail: Optional[str] = None,
) -> bool:
    """Stamp the run settled and clear it from the queue.

    ``charged_credits`` is the console's own figure when it names one; it is
    what makes the run reconcilable against the ledger. ``None`` leaves it
    unset rather than writing a zero the console never confirmed.
    """
    async with pool.get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE conversation_responses
                SET billing_settled_at = NOW(),
                    billing_settle_pending = FALSE,
                    billing_charged_credits = COALESCE(%s, billing_charged_credits),
                    billing_settle_error = %s
                WHERE conversation_response_id = %s
                  AND billing_settled_at IS NULL
                """,
                (charged_credits, _error_text(detail), run_id),
            )
            return cur.rowcount == 1


async def list_settle_pending(
    limit: int = 100, *, grace_seconds: int = 120
) -> List[Dict[str, Any]]:
    """Pending runs old enough to settle, oldest first, with their usage row.

    The lateral join takes the newest non-task usage row for the run — the main
    agent's, not a subagent's, since subagent usage is charged on its own path.
    A pending run whose finalize has not committed that row yet simply does not
    appear; it will on a later cycle.
    """
    async with pool.get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    r.conversation_response_id AS run_id,
                    COALESCE(r.user_id, u.user_id) AS user_id,
                    r.billing_settle_error AS last_error,
                    r.created_at AS run_created_at,
                    u.conversation_usage_id,
                    u.token_usage,
                    u.is_byok,
                    u.total_credits,
                    u.token_credits,
                    u.infrastructure_credits
                FROM conversation_responses r
                JOIN LATERAL (
                    SELECT *
                    FROM conversation_usages u
                    WHERE u.conversation_response_id = r.conversation_response_id
                      AND u.msg_type <> 'task'
                    ORDER BY u.created_at DESC
                    LIMIT 1
                ) u ON TRUE
                WHERE r.billing_settle_pending
                  AND r.billing_settled_at IS NULL
                  AND r.billing_settle_pending_at
                      <= NOW() - make_interval(secs => %s)
                ORDER BY r.billing_settle_pending_at, r.conversation_response_id
                LIMIT %s
                """,
                (grace_seconds, limit),
            )
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


async def count_settle_pending(*, grace_seconds: int = 0) -> int:
    """How many runs are waiting to settle, for the worker's log line."""
    async with pool.get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*)
                FROM conversation_responses
                WHERE billing_settle_pending
                  AND billing_settled_at IS NULL
                  AND billing_settle_pending_at
                      <= NOW() - make_interval(secs => %s)
                """,
                (grace_seconds,),
            )
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0


async def count_pending_without_usage(*, grace_seconds: int = 3600) -> int:
    """Pending runs old enough that finalize should have committed a usage row.

    A non-zero count is a signal, not something the worker can fix: those runs
    have no durable spend to settle from. Logged once per cycle so an operator
    sees them (a finalize failure, or a run that was never finalized).
    """
    async with pool.get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*)
                FROM conversation_responses r
                WHERE r.billing_settle_pending
                  AND r.billing_settled_at IS NULL
                  AND r.billing_settle_pending_at
                      <= NOW() - make_interval(secs => %s)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM conversation_usages u
                      WHERE u.conversation_response_id = r.conversation_response_id
                        AND u.msg_type <> 'task'
                  )
                """,
                (grace_seconds,),
            )
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0


__all__ = [
    "count_pending_without_usage",
    "count_settle_pending",
    "list_settle_pending",
    "mark_settle_error",
    "mark_settle_pending",
    "mark_settled",
]
