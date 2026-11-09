"""Server-rendered admin pages (Jinja2). Same service layer as the JSON API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .admin_service import (
    adjust_credits,
    assign_plan,
    create_plan,
    release_lease,
    update_plan,
    user_bundle,
)
from .auth import ADMIN_COOKIE, issue_admin_cookie, serializer, settings_of
from .db import pool
from .store import (
    count_users,
    dashboard_stats,
    list_audit,
    list_ledger,
    list_plans,
    list_users,
)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
router = APIRouter(prefix="/admin", tags=["Admin UI"])

PAGE_SIZE = 50


def _redirect(url: str, msg: str = "") -> RedirectResponse:
    if msg:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urlencode({'msg': msg})}"
    return RedirectResponse(url, status_code=303)


def page_actor(request: Request) -> str:
    """The admin behind a page request, or a redirect to the login form."""
    settings = settings_of(request)
    raw = request.cookies.get(ADMIN_COOKIE, "")
    if raw:
        try:
            data = serializer(settings).loads(
                raw, max_age=settings.cookie_max_age_seconds
            )
            return str(data.get("actor", "admin"))
        except Exception:  # noqa: BLE001 - any bad cookie means log in again
            pass
    raise HTTPException(status_code=303, headers={"Location": "/admin/login"})


def _json_or(raw: str, default: Any) -> Any:
    raw = (raw or "").strip()
    if not raw:
        return default
    return json.loads(raw)


def _render(request: Request, name: str, **context) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name=name,
        context={"request": request, "msg": request.query_params.get("msg", ""), **context},
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _render(request, "login.html")


@router.post("/login")
async def login(request: Request, token: str = Form("")):
    settings = settings_of(request)
    import hmac

    if not hmac.compare_digest(token.encode(), settings.admin_token.encode()):
        return _render(request, "login.html", error="令牌不正确")
    response = _redirect("/admin")
    response.set_cookie(
        ADMIN_COOKIE,
        issue_admin_cookie(settings),
        max_age=settings.cookie_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/logout")
async def logout():
    response = _redirect("/admin/login")
    response.delete_cookie(ADMIN_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request):
    actor = page_actor(request)
    settings = settings_of(request)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            stats = await dashboard_stats(cur, settings.default_plan)
    return _render(request, "dashboard.html", actor=actor, stats=stats)


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request, q: str = "", plan: str = "", page: int = 1
):
    actor = page_actor(request)
    settings = settings_of(request)
    page = max(page, 1)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            users = await list_users(
                cur,
                default_plan=settings.default_plan,
                query=q,
                plan=plan,
                limit=PAGE_SIZE,
                offset=(page - 1) * PAGE_SIZE,
            )
            total = await count_users(
                cur, default_plan=settings.default_plan, query=q, plan=plan
            )
            plans = await list_plans(cur)
    return _render(
        request,
        "users.html",
        actor=actor,
        users=users,
        plans=plans,
        total=total,
        page=page,
        page_size=PAGE_SIZE,
        q=q,
        plan=plan,
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_page(request: Request, user_id: str):
    actor = page_actor(request)
    settings = settings_of(request)
    bundle = await user_bundle(user_id, settings)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            plans = await list_plans(cur)
    return _render(
        request,
        "user_detail.html",
        actor=actor,
        bundle=bundle,
        plans=plans,
    )


@router.get("/plans", response_class=HTMLResponse)
async def plans_page(request: Request):
    actor = page_actor(request)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            plans = await list_plans(cur)
    return _render(request, "plans.html", actor=actor, plans=plans)


@router.get("/ledger", response_class=HTMLResponse)
async def ledger_page(
    request: Request, user_id: str = "", reason: str = "", page: int = 1
):
    actor = page_actor(request)
    page = max(page, 1)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            entries = await list_ledger(
                cur,
                user_id=user_id,
                reason=reason,
                limit=PAGE_SIZE,
                offset=(page - 1) * PAGE_SIZE,
            )
    return _render(
        request,
        "ledger.html",
        actor=actor,
        entries=entries,
        user_id=user_id,
        reason=reason,
        page=page,
        page_size=PAGE_SIZE,
    )


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, page: int = 1):
    actor = page_actor(request)
    page = max(page, 1)
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            entries = await list_audit(
                cur, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
            )
    return _render(request, "audit.html", actor=actor, entries=entries, page=page)


# ---------------------------------------------------------------------------
# Form actions (POST + redirect)
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/plan")
async def form_assign_plan(
    request: Request,
    user_id: str,
    plan_code: str = Form(...),
    note: str = Form(""),
    grant_month: Optional[str] = Form(None),
):
    actor = page_actor(request)
    try:
        granted = await assign_plan(
            user_id=user_id,
            plan_code=plan_code,
            note=note or None,
            grant_month_flag=grant_month is not None,
            actor=actor,
            settings=settings_of(request),
        )
        msg = "套餐已更新" + ("，已发放本月积分" if granted else "")
    except HTTPException as e:
        msg = f"失败：{e.detail}"
    return _redirect(f"/admin/users/{user_id}", msg)


@router.post("/users/{user_id}/credits")
async def form_credits(
    request: Request,
    user_id: str,
    delta: float = Form(...),
    reason: str = Form("topup"),
    note: str = Form(""),
):
    actor = page_actor(request)
    try:
        await adjust_credits(
            user_id=user_id, delta=delta, reason=reason, note=note or None, actor=actor
        )
        msg = f"已记账 {delta:+.2f} 积分"
    except HTTPException as e:
        msg = f"失败：{e.detail}"
    return _redirect(f"/admin/users/{user_id}", msg)


@router.post("/users/{user_id}/leases/{run_ref}/release")
async def form_release_lease(request: Request, user_id: str, run_ref: str):
    actor = page_actor(request)
    try:
        await release_lease(user_id=user_id, run_ref=run_ref, actor=actor)
        msg = "租约已释放"
    except HTTPException as e:
        msg = f"失败：{e.detail}"
    return _redirect(f"/admin/users/{user_id}", msg)


@router.post("/plans")
async def form_create_plan(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    access_tier: int = Form(0),
    scopes: str = Form(""),
    limits: str = Form("{}"),
    sandbox_pricing: str = Form("{}"),
    monthly_credits: float = Form(0),
    price_cny: float = Form(0),
    included_hours_month: float = Form(0),
):
    actor = page_actor(request)
    try:
        await create_plan(
            payload={
                "code": code.strip(),
                "name": name.strip(),
                "description": description or None,
                "access_tier": access_tier,
                "scopes": [s.strip() for s in scopes.split(",") if s.strip()],
                "limits": _json_or(limits, {}),
                "sandbox_pricing": _json_or(sandbox_pricing, {}),
                "monthly_credits": monthly_credits,
                "price_cny": price_cny,
                "included_hours_month": included_hours_month,
            },
            actor=actor,
        )
        msg = "套餐已创建"
    except HTTPException as e:
        msg = f"失败：{e.detail}"
    except json.JSONDecodeError:
        msg = "失败：limits / pricing 不是合法 JSON"
    return _redirect("/admin/plans", msg)


@router.post("/plans/{code}")
async def form_update_plan(
    request: Request,
    code: str,
    name: str = Form(...),
    description: str = Form(""),
    access_tier: int = Form(0),
    scopes: str = Form(""),
    limits: str = Form("{}"),
    sandbox_pricing: str = Form("{}"),
    monthly_credits: float = Form(0),
    price_cny: float = Form(0),
    included_hours_month: float = Form(0),
):
    actor = page_actor(request)
    try:
        await update_plan(
            code=code,
            payload={
                "code": code,
                "name": name.strip(),
                "description": description or None,
                "access_tier": access_tier,
                "scopes": [s.strip() for s in scopes.split(",") if s.strip()],
                "limits": _json_or(limits, {}),
                "sandbox_pricing": _json_or(sandbox_pricing, {}),
                "monthly_credits": monthly_credits,
                "price_cny": price_cny,
                "included_hours_month": included_hours_month,
            },
            actor=actor,
        )
        msg = "套餐已更新"
    except HTTPException as e:
        msg = f"失败：{e.detail}"
    except json.JSONDecodeError:
        msg = "失败：limits / pricing 不是合法 JSON"
    return _redirect("/admin/plans", msg)
