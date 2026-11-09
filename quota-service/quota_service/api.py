"""The contract LangAlpha calls: validate plus the runtime credit leases."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import service_user
from .db import fetch_one, pool
from .leases import acquire, release
from .quota import build_quota
from .store import (
    computer_counts,
    load_plan,
    reserved_credits,
    used_credits_month,
    wallet_balance,
)

router = APIRouter(tags=["LangAlpha"])


class ValidateRequest(BaseModel):
    check_quota: Optional[str] = None
    byok: bool = False
    surface: Optional[str] = None


@router.post("/api/auth/validate")
async def validate(
    request: Request,
    body: ValidateRequest,
    user_id: str = Depends(service_user),
):
    """Membership plus the named quota.

    LangAlpha sends ``check_quota`` per gate; an empty one only wants the
    plan/tier (``/users/me``). The counts are read from the shared database,
    so they always match what the backend itself would count.
    """
    settings = request.app.state.settings
    counts = {}
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            plan = await load_plan(cur, user_id, settings.default_plan)
            if body.check_quota in (
                "computer_count",
                "workspace",
                "always_on",
                "spec_performance",
                "spec_max",
                "spec_xlarge",
            ):
                counts = await computer_counts(cur, user_id)
            balance = await wallet_balance(cur, user_id)
            reserved = await reserved_credits(cur, user_id)
            used = await used_credits_month(cur, user_id)

    quota = build_quota(
        check_quota=body.check_quota,
        plan=plan,
        balance=balance,
        reserved=reserved,
        used_credits_month=used,
        counts=counts,
        byok=body.byok,
    )
    return {
        "access_tier": plan.access_tier,
        "plan_display_name": plan.name,
        "scopes": list(plan.scopes),
        "quota": quota,
    }


@router.get("/api/auth/billing/leases/capability")
async def capability(request: Request):
    """Readiness probe: LangAlpha checks this at boot before gating turns."""
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            await cur.fetchone()
    return {"name": "quota-service", "version": 1, "leases": True}


class AcquireRequest(BaseModel):
    user_id: Optional[str] = None
    run_ref: str = Field(min_length=1, max_length=200)
    spent_credits: float = 0.0
    rate_multiplier: float = 1.0
    byok: bool = False


@router.post("/api/auth/billing/leases/acquire")
async def lease_acquire(
    request: Request,
    body: AcquireRequest,
    user_id: str = Depends(service_user),
):
    if body.user_id and body.user_id != user_id:
        raise HTTPException(status_code=400, detail="user_id does not match X-User-Id")
    settings = request.app.state.settings
    return await acquire(
        user_id=user_id,
        run_ref=body.run_ref,
        spent_credits=max(float(body.spent_credits), 0.0),
        rate_multiplier=float(body.rate_multiplier),
        byok=bool(body.byok),
        settings=settings,
    )


class ReleaseRequest(BaseModel):
    user_id: Optional[str] = None
    run_ref: str = Field(min_length=1, max_length=200)
    generation: Optional[int] = None


@router.post("/api/auth/billing/leases/release")
async def lease_release(
    body: ReleaseRequest,
    user_id: str = Depends(service_user),
):
    if body.user_id and body.user_id != user_id:
        raise HTTPException(status_code=400, detail="user_id does not match X-User-Id")
    released = await release(
        user_id=user_id, run_ref=body.run_ref, generation=body.generation
    )
    if not released:
        # The contract treats 404 as the idempotent "nothing to release".
        raise HTTPException(status_code=404, detail="no such lease")
    return {"released": True}
