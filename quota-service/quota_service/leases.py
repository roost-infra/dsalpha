"""Runtime credit leases: reserve a turn's spend, release it when the turn ends.

A lease is a *reservation*, never a charge. Actual spend is booked later from
``conversation_usages`` (M2), so the reservation only has to make sure the
available balance cannot be promised to two turns at once.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from .config import Settings
from .db import pool
from .quota import available_credits, build_quota, per_turn_cap
from .store import load_plan, reserved_credits, used_credits_month, wallet_balance


async def acquire(
    *,
    user_id: str,
    run_ref: str,
    spent_credits: float,
    rate_multiplier: float,
    byok: bool,
    settings: Settings,
) -> dict:
    """Grant (or extend) one run's ceiling.

    Re-acquiring the same ``run_ref`` is the gate's heartbeat: the caller's
    ``spent_credits`` is cumulative, and this replaces the reservation rather
    than adding to it. ``generation`` fences a release that races a rejoin.
    """
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                plan = await load_plan(cur, user_id, settings.default_plan)

                # Row-lock the wallet so two concurrent acquires for one user
                # cannot both compute the same available balance.
                await cur.execute(
                    "INSERT INTO billing.wallets (user_id) VALUES (%s) "
                    "ON CONFLICT DO NOTHING",
                    (user_id,),
                )
                await cur.execute(
                    "SELECT balance FROM billing.wallets WHERE user_id = %s FOR UPDATE",
                    (user_id,),
                )
                balance = float((await cur.fetchone())["balance"])

                others = await reserved_credits(cur, user_id, exclude_run=run_ref)

                await cur.execute(
                    "SELECT user_id, generation FROM billing.leases "
                    "WHERE run_ref = %s FOR UPDATE",
                    (run_ref,),
                )
                existing = await cur.fetchone()
                if existing is not None and existing["user_id"] != user_id:
                    raise HTTPException(
                        status_code=409,
                        detail="run_ref belongs to another user",
                    )

                cap = per_turn_cap(plan, settings.per_turn_credits)
                if byok:
                    granted = True
                    ceiling = round(cap, 6)
                    reserved = 0.0
                else:
                    available = available_credits(balance, others)
                    ceiling = round(min(max(available, 0.0), cap), 6)
                    granted = ceiling > 0
                    reserved = ceiling if granted else 0.0

                generation = int(existing["generation"]) + 1 if existing else 1
                await cur.execute(
                    """
                    INSERT INTO billing.leases
                        (run_ref, user_id, reserved_credits, generation, expires_at)
                    VALUES (%s, %s, %s, %s, now() + make_interval(secs => %s))
                    ON CONFLICT (run_ref) DO UPDATE SET
                        reserved_credits = EXCLUDED.reserved_credits,
                        generation = EXCLUDED.generation,
                        expires_at = EXCLUDED.expires_at,
                        released_at = NULL
                    """,
                    (run_ref, user_id, reserved, generation, settings.lease_ttl_seconds),
                )

                used = await used_credits_month(cur, user_id)
                quota = build_quota(
                    check_quota="chat",
                    plan=plan,
                    balance=balance,
                    reserved=others + reserved,
                    used_credits_month=used,
                    counts={},
                    byok=byok,
                )

    return {
        "granted": granted,
        "ceiling_credits": ceiling if granted else 0.0,
        "ttl_seconds": settings.lease_ttl_seconds,
        "generation": generation,
        "quota": quota,
    }


async def release(
    *, user_id: str, run_ref: str, generation: Optional[int]
) -> bool:
    """Retire a run's reservation. Idempotent: False when there was none."""
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                if generation is None:
                    await cur.execute(
                        "UPDATE billing.leases SET released_at = now() "
                        "WHERE run_ref = %s AND user_id = %s AND released_at IS NULL",
                        (run_ref, user_id),
                    )
                else:
                    await cur.execute(
                        "UPDATE billing.leases SET released_at = now() "
                        "WHERE run_ref = %s AND user_id = %s AND released_at IS NULL "
                        "AND generation = %s",
                        (run_ref, user_id, generation),
                    )
                return cur.rowcount > 0


async def expired_leases(user_id: str) -> int:
    """Housekeeping helper for the admin page: live leases that already lapsed."""
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT count(*) AS n FROM billing.leases "
                "WHERE user_id = %s AND released_at IS NULL AND expires_at < now()",
                (user_id,),
            )
            return int((await cur.fetchone())["n"])
