"""Operational upkeep for the bots layer: leases, retries, retention.

Run inside the backend container with the app's env. Without ``--apply`` every
action only counts what it would touch.

    /app/.venv/bin/python scripts/bots_rooms_maintenance.py
    /app/.venv/bin/python scripts/bots_rooms_maintenance.py --apply
    /app/.venv/bin/python scripts/bots_rooms_maintenance.py --apply --prune-days 30
    /app/.venv/bin/python scripts/bots_rooms_maintenance.py --apply --close-assignments

Actions:
- release stale delivery leases (a worker died mid-attempt);
- fail queued bot messages that spent their attempts (a crash on the last one);
- prune terminal bot messages, closed assignments and old bot versions;
- trim room_log rows older than ``--prune-days`` (read cursors are GREATEST'd
  seqs, so an older row going away only means less history).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from scripts.utils._thread_job import app_infra  # noqa: E402


async def _one(sql: str, params: tuple = ()) -> int:
    from src.server.database.pool import get_db_connection

    async with get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return int(cur.rowcount)


async def _count(sql: str, params: tuple = ()) -> int:
    from src.server.database.pool import get_db_connection

    async with get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def main(args: argparse.Namespace) -> int:
    dry = not args.apply
    print(f"bots/rooms maintenance — {'DRY RUN' if dry else 'APPLY'}")

    stale = await _count(
        "SELECT COUNT(*) FROM bot_messages WHERE status = 'queued' "
        "AND delivering_until IS NOT NULL AND delivering_until < NOW()"
    )
    print(f"stale delivery leases: {stale}")
    exhausted = await _count(
        "SELECT COUNT(*) FROM bot_messages WHERE status = 'queued' AND attempts >= 5"
    )
    print(f"queued messages out of attempts: {exhausted}")
    terminal = await _count(
        "SELECT COUNT(*) FROM bot_messages WHERE status IN ('failed', 'consumed') "
        "AND created_at < NOW() - make_interval(days => %s)",
        (args.prune_days,),
    )
    old_log = await _count(
        "SELECT COUNT(*) FROM room_log "
        "WHERE created_at < NOW() - make_interval(days => %s)",
        (args.prune_days,),
    )
    old_versions = await _count(
        "SELECT COUNT(*) FROM bot_versions "
        "WHERE created_at < NOW() - make_interval(days => %s)",
        (args.prune_days,),
    )
    stale_assignments = await _count(
        "SELECT COUNT(*) FROM assignments "
        "WHERE status IN ('requested', 'working', 'needs_input') "
        "AND created_at < NOW() - make_interval(days => %s)",
        (args.stale_assignment_days,),
    )
    print(f"terminal bot messages older than {args.prune_days}d: {terminal}")
    print(f"room log rows older than {args.prune_days}d: {old_log}")
    print(f"bot versions older than {args.prune_days}d: {old_versions}")
    print(
        f"open assignments older than {args.stale_assignment_days}d: "
        f"{stale_assignments}"
    )

    if dry:
        print("Dry run: rerun with --apply to write.")
        return 0

    released = await _one(
        "UPDATE bot_messages SET delivering_until = NULL "
        "WHERE status = 'queued' AND delivering_until IS NOT NULL "
        "AND delivering_until < NOW()"
    )
    failed = await _one(
        "UPDATE bot_messages SET status = 'failed', delivering_until = NULL "
        "WHERE status = 'queued' AND attempts >= 5"
    )
    deleted_messages = await _one(
        "DELETE FROM bot_messages WHERE status IN ('failed', 'consumed') "
        "AND created_at < NOW() - make_interval(days => %s)",
        (args.prune_days,),
    )
    deleted_log = await _one(
        "DELETE FROM room_log "
        "WHERE created_at < NOW() - make_interval(days => %s)",
        (args.prune_days,),
    )
    deleted_versions = await _one(
        "DELETE FROM bot_versions "
        "WHERE created_at < NOW() - make_interval(days => %s)",
        (args.prune_days,),
    )
    closed = 0
    if args.close_assignments:
        closed = await _one(
            "UPDATE assignments SET status = 'cancelled', outcome = 'timeout', "
            "closed_at = NOW(), updated_at = NOW() "
            "WHERE status IN ('requested', 'working', 'needs_input') "
            "AND created_at < NOW() - make_interval(days => %s)",
            (args.stale_assignment_days,),
        )
    print(
        f"released {released} lease(s); failed {failed} exhausted; "
        f"deleted {deleted_messages} message(s), {deleted_log} room row(s), "
        f"{deleted_versions} version(s); cancelled {closed} assignment(s)"
    )
    return 0


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument(
        "--prune-days", type=int, default=90, help="retention window (default 90)"
    )
    parser.add_argument(
        "--stale-assignment-days",
        type=int,
        default=7,
        help="age after which an open assignment may be cancelled (default 7)",
    )
    parser.add_argument(
        "--close-assignments",
        action="store_true",
        help="cancel open assignments past the stale window",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(_parse())))
