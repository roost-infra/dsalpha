"""Administrative operations, shared by the JSON API and the HTML pages."""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional

from fastapi import HTTPException
from psycopg.types.json import Json

from .config import Settings
from .credits import add_credits, grant_month
from .db import pool
from .store import (
    active_leases,
    audit,
    plan_exists,
    plan_code_of,
    recent_ledger,
    token_usage_report,
    user_detail,
)


async def assign_plan(
    *,
    user_id: str,
    plan_code: str,
    note: Optional[str],
    grant_month_flag: bool,
    actor: str,
    settings: Settings,
) -> bool:
    """Point the user at a plan; optionally grant its monthly credits now."""
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                if not await plan_exists(cur, plan_code):
                    raise HTTPException(status_code=422, detail=f"unknown plan {plan_code!r}")
                await cur.execute(
                    """
                    INSERT INTO billing.user_plans (user_id, plan_code, assigned_by, note)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        plan_code = EXCLUDED.plan_code,
                        assigned_by = EXCLUDED.assigned_by,
                        assigned_at = now(),
                        note = EXCLUDED.note
                    """,
                    (user_id, plan_code, actor, note),
                )
                await audit(
                    cur,
                    actor=actor,
                    action="assign_plan",
                    target=user_id,
                    detail={"plan_code": plan_code, "note": note},
                )
                granted = False
                if grant_month_flag:
                    await cur.execute(
                        "SELECT monthly_credits FROM billing.plans WHERE code = %s",
                        (plan_code,),
                    )
                    row = await cur.fetchone()
                    credits = float(row["monthly_credits"]) if row else 0.0
                    granted = await grant_month(
                        cur,
                        user_id=user_id,
                        credits=credits,
                        tz=settings.monthly_grant_tz,
                        actor=actor,
                    )
    return granted


async def adjust_credits(
    *,
    user_id: str,
    delta: float,
    reason: str,
    note: Optional[str],
    actor: str,
) -> None:
    if delta == 0:
        raise HTTPException(status_code=422, detail="delta must not be zero")
    # The service is not a payment processor: only topups and corrections reach
    # this path. Usage reasons are written by the ingestion job, not an admin.
    if reason not in ("topup", "adjust"):
        raise HTTPException(status_code=422, detail="reason must be topup or adjust")
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await add_credits(
                    cur,
                    user_id=user_id,
                    delta=float(delta),
                    reason=reason,
                    source="manual",
                    source_id=str(uuid.uuid4()),
                    actor=actor,
                    note=note,
                )


async def release_lease(*, user_id: str, run_ref: str, actor: str) -> None:
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE billing.leases SET released_at = now() "
                    "WHERE run_ref = %s AND user_id = %s AND released_at IS NULL",
                    (run_ref, user_id),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="no such live lease")
                await audit(
                    cur,
                    actor=actor,
                    action="release_lease",
                    target=run_ref,
                    detail={"user_id": user_id},
                )


async def create_plan(*, payload: Mapping[str, Any], actor: str) -> None:
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                if await plan_exists(cur, str(payload["code"])):
                    raise HTTPException(status_code=409, detail="plan already exists")
                await _write_plan(cur, payload, actor, create=True)


async def update_plan(*, code: str, payload: Mapping[str, Any], actor: str) -> None:
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                if not await plan_exists(cur, code):
                    raise HTTPException(status_code=404, detail="no such plan")
                await _write_plan(cur, {**payload, "code": code}, actor, create=False)


async def _write_plan(cur, payload: Mapping[str, Any], actor: str, *, create: bool) -> None:
    code = str(payload["code"])
    values = (
        str(payload.get("name") or code),
        payload.get("description"),
        int(payload.get("access_tier") or 0),
        list(payload.get("scopes") or []),
        Json(dict(payload.get("limits") or {})),
        Json(dict(payload.get("sandbox_pricing") or {})),
        float(payload.get("monthly_credits") or 0),
        float(payload.get("price_cny") or 0),
        float(payload.get("included_hours_month") or 0),
    )
    if create:
        await cur.execute(
            "INSERT INTO billing.plans "
            "(code, name, description, access_tier, scopes, limits, "
            " sandbox_pricing, monthly_credits, price_cny, included_hours_month) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (code, *values),
        )
    else:
        await cur.execute(
            "UPDATE billing.plans SET name = %s, description = %s, "
            "access_tier = %s, scopes = %s, limits = %s, sandbox_pricing = %s, "
            "monthly_credits = %s, price_cny = %s, included_hours_month = %s, "
            "updated_at = now() WHERE code = %s",
            (*values, code),
        )
    await audit(
        cur,
        actor=actor,
        action="create_plan" if create else "update_plan",
        target=code,
        detail={"name": values[0]},
    )


async def user_bundle(
    user_id: str, settings: Settings, *, usage_days: int = 30
) -> dict:
    """Everything the admin user page shows, in one read transaction."""
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            user = await user_detail(cur, user_id, settings.default_plan)
            if user is None:
                raise HTTPException(status_code=404, detail="user not found")
            return {
                "user": user,
                "ledger": await recent_ledger(cur, user_id),
                "leases": await active_leases(cur, user_id),
                "plan_code": await plan_code_of(cur, user_id, settings.default_plan),
                "usage": await token_usage_report(cur, user_id, usage_days),
            }
