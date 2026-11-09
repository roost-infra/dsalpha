"""Wallet and ledger writes shared by admin actions and (M2) usage ingestion."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from psycopg import AsyncCursor

from .store import audit


async def add_credits(
    cur: AsyncCursor,
    *,
    user_id: str,
    delta: float,
    reason: str,
    source: str,
    source_id: str,
    actor: Optional[str] = None,
    note: Optional[str] = None,
) -> bool:
    """Book one ledger entry and move the wallet, atomically and idempotently.

    Returns False when ``(source, source_id)`` was already booked: a retried
    grant or recharge must not move the balance twice.
    """
    await cur.execute(
        "INSERT INTO billing.ledger (user_id, delta, reason, source, source_id) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (source, source_id) DO NOTHING",
        (user_id, delta, reason, source, source_id),
    )
    if cur.rowcount == 0:
        return False

    await cur.execute(
        "INSERT INTO billing.wallets (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
        (user_id,),
    )
    await cur.execute(
        "UPDATE billing.wallets SET balance = balance + %s, updated_at = now() "
        "WHERE user_id = %s",
        (delta, user_id),
    )
    if actor:
        await audit(
            cur,
            actor=actor,
            action=reason,
            target=user_id,
            detail={"delta": delta, "source": source, "source_id": source_id, "note": note},
        )
    return True


def current_month(tz: str) -> str:
    return datetime.now(ZoneInfo(tz)).strftime("%Y-%m")


async def grant_month(
    cur: AsyncCursor,
    *,
    user_id: str,
    credits: float,
    tz: str,
    actor: Optional[str] = None,
) -> bool:
    """Grant this month's plan credits once per user per month."""
    if credits <= 0:
        return False
    return await add_credits(
        cur,
        user_id=user_id,
        delta=float(credits),
        reason="grant",
        source="grant",
        source_id=f"{user_id}:{current_month(tz)}",
        actor=actor,
        note="monthly plan credits",
    )
