"""JSON admin API. The HTML pages use the same service functions."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .admin_service import (
    adjust_credits,
    assign_plan,
    create_plan,
    release_lease,
    update_plan,
    user_bundle,
)
from .auth import admin_actor
from .db import pool
from .store import (
    count_users,
    dashboard_stats,
    list_audit,
    list_ledger,
    list_plans,
    list_users,
    token_usage_report,
)

router = APIRouter(prefix="/admin/api", tags=["Admin API"])


class AssignPlanRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=32)
    note: Optional[str] = None
    grant_month: bool = False


class CreditsRequest(BaseModel):
    delta: float
    reason: str = "topup"
    note: Optional[str] = None


class PlanBody(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    name: str
    description: Optional[str] = None
    access_tier: int = 0
    scopes: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    sandbox_pricing: dict[str, Any] = Field(default_factory=dict)
    monthly_credits: float = 0.0
    price_cny: float = 0.0
    included_hours_month: float = 0.0


def _settings(request: Request):
    return request.app.state.settings


@router.get("/dashboard")
async def api_dashboard(request: Request, actor: str = Depends(admin_actor)):
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            return await dashboard_stats(cur, _settings(request).default_plan)


@router.get("/users")
async def api_users(
    request: Request,
    q: str = "",
    plan: str = "",
    page: int = 1,
    page_size: int = 50,
    actor: str = Depends(admin_actor),
):
    settings = _settings(request)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            users = await list_users(
                cur,
                default_plan=settings.default_plan,
                query=q,
                plan=plan,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
            total = await count_users(
                cur, default_plan=settings.default_plan, query=q, plan=plan
            )
    return {"users": users, "total": total, "page": page, "page_size": page_size}


@router.get("/users/{user_id}")
async def api_user(
    request: Request, user_id: str, actor: str = Depends(admin_actor)
):
    return await user_bundle(user_id, _settings(request))


@router.get("/users/{user_id}/usage")
async def api_user_usage(
    request: Request,
    user_id: str,
    days: int = 30,
    actor: str = Depends(admin_actor),
):
    days = min(max(days, 1), 365)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            return await token_usage_report(cur, user_id, days)


@router.post("/users/{user_id}/plan")
async def api_assign_plan(
    request: Request,
    user_id: str,
    body: AssignPlanRequest,
    actor: str = Depends(admin_actor),
):
    granted = await assign_plan(
        user_id=user_id,
        plan_code=body.plan_code,
        note=body.note,
        grant_month_flag=body.grant_month,
        actor=actor,
        settings=_settings(request),
    )
    return {"ok": True, "granted": granted}


@router.post("/users/{user_id}/credits")
async def api_credits(
    request: Request,
    user_id: str,
    body: CreditsRequest,
    actor: str = Depends(admin_actor),
):
    await adjust_credits(
        user_id=user_id,
        delta=body.delta,
        reason=body.reason,
        note=body.note,
        actor=actor,
    )
    return {"ok": True}


@router.post("/users/{user_id}/leases/{run_ref}/release")
async def api_release_lease(
    user_id: str, run_ref: str, actor: str = Depends(admin_actor)
):
    await release_lease(user_id=user_id, run_ref=run_ref, actor=actor)
    return {"ok": True}


@router.get("/plans")
async def api_plans(actor: str = Depends(admin_actor)):
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            return {"plans": await list_plans(cur)}


@router.post("/plans")
async def api_create_plan(body: PlanBody, actor: str = Depends(admin_actor)):
    await create_plan(payload=body.model_dump(), actor=actor)
    return {"ok": True}


@router.put("/plans/{code}")
async def api_update_plan(
    code: str, body: PlanBody, actor: str = Depends(admin_actor)
):
    await update_plan(code=code, payload=body.model_dump(), actor=actor)
    return {"ok": True}


@router.get("/ledger")
async def api_ledger(
    request: Request,
    user_id: str = "",
    reason: str = "",
    page: int = 1,
    page_size: int = 100,
    actor: str = Depends(admin_actor),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 500)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            entries = await list_ledger(
                cur,
                user_id=user_id,
                reason=reason,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
    return {"entries": entries}


@router.get("/audit")
async def api_audit(
    page: int = 1,
    page_size: int = 100,
    actor: str = Depends(admin_actor),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 500)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            entries = await list_audit(
                cur, limit=page_size, offset=(page - 1) * page_size
            )
    return {"entries": entries}
