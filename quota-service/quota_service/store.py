"""Read queries shared by validate, leases and the admin pages."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from psycopg import AsyncCursor

from .quota import Plan, plan_from_row

_PLAN_COLS = (
    "p.code, p.name, p.access_tier, p.scopes, p.limits, "
    "p.sandbox_pricing, p.monthly_credits, p.price_cny, p.included_hours_month"
)


async def load_plan(cur: AsyncCursor, user_id: str, default_code: str) -> Plan:
    """The user's assigned plan, else the deployment default."""
    await cur.execute(
        f"SELECT {_PLAN_COLS} FROM billing.user_plans up "
        "JOIN billing.plans p ON p.code = up.plan_code WHERE up.user_id = %s",
        (user_id,),
    )
    row = await cur.fetchone()
    if row is None:
        await cur.execute(
            f"SELECT {_PLAN_COLS} FROM billing.plans p WHERE p.code = %s",
            (default_code,),
        )
        row = await cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"no plan assigned to {user_id!r} and default plan {default_code!r} missing"
        )
    return plan_from_row(row)


async def wallet_balance(cur: AsyncCursor, user_id: str) -> float:
    await cur.execute(
        "SELECT balance FROM billing.wallets WHERE user_id = %s", (user_id,)
    )
    row = await cur.fetchone()
    return float(row["balance"]) if row else 0.0


async def reserved_credits(
    cur: AsyncCursor, user_id: str, *, exclude_run: Optional[str] = None
) -> float:
    """Credits held by this user's live leases, optionally ignoring one run."""
    if exclude_run is None:
        await cur.execute(
            "SELECT COALESCE(SUM(reserved_credits), 0) AS reserved "
            "FROM billing.leases WHERE user_id = %s "
            "AND released_at IS NULL AND expires_at > now()",
            (user_id,),
        )
    else:
        await cur.execute(
            "SELECT COALESCE(SUM(reserved_credits), 0) AS reserved "
            "FROM billing.leases WHERE user_id = %s "
            "AND released_at IS NULL AND expires_at > now() AND run_ref <> %s",
            (user_id, exclude_run),
        )
    row = await cur.fetchone()
    return float(row["reserved"]) if row else 0.0


async def computer_counts(cur: AsyncCursor, user_id: str) -> Mapping[str, int]:
    """The four counts dsalpha's capacity gates ask about, read live.

    The quota service shares the dsalpha database, so these are the same
    rows the backend itself would count.
    """
    await cur.execute(
        """
        SELECT
            count(*) FILTER (WHERE status NOT IN ('deleted', 'unbound'))
                AS computer_count,
            count(*) FILTER (WHERE status IN ('running', 'starting', 'stopping'))
                AS live_count,
            count(*) FILTER (
                WHERE is_always_on AND status NOT IN ('deleted', 'unbound')
            ) AS always_on,
            count(*) FILTER (
                WHERE resource_tier IN ('performance', 'max', 'xlarge')
                  AND status NOT IN ('deleted', 'unbound')
            ) AS spec_count
        FROM public.computers
        WHERE user_id = %s
        """,
        (user_id,),
    )
    row = await cur.fetchone() or {}
    keys = ("computer_count", "live_count", "always_on", "spec_count")
    return {key: int(row.get(key) or 0) for key in keys}


async def used_credits_month(cur: AsyncCursor, user_id: str) -> float:
    """What this user has been charged since the start of the current month."""
    await cur.execute(
        """
        SELECT COALESCE(-SUM(delta), 0) AS used
        FROM billing.ledger
        WHERE user_id = %s AND delta < 0
          AND created_at >= date_trunc('month', now())
        """,
        (user_id,),
    )
    row = await cur.fetchone() or {}
    return float(row.get("used") or 0)


async def audit(
    cur: AsyncCursor,
    *,
    actor: str,
    action: str,
    target: Optional[str],
    detail: Mapping[str, Any],
) -> None:
    from psycopg.types.json import Json

    await cur.execute(
        "INSERT INTO billing.admin_audit (actor, action, target, detail) "
        "VALUES (%s, %s, %s, %s)",
        (actor, action, target, Json(dict(detail))),
    )


# ---------------------------------------------------------------------------
# Admin read helpers
# ---------------------------------------------------------------------------

_USER_COLS = """
    u.user_id, u.email, u.name, u.created_at,
    COALESCE(up.plan_code, %(default_plan)s) AS plan_code,
    COALESCE(p.name, dp.name) AS plan_name,
    COALESCE(w.balance, 0) AS balance
"""

_USER_FROM = """
    FROM public.users u
    LEFT JOIN billing.user_plans up ON up.user_id = u.user_id
    LEFT JOIN billing.plans p ON p.code = up.plan_code
    LEFT JOIN billing.plans dp ON dp.code = %(default_plan)s
    LEFT JOIN billing.wallets w ON w.user_id = u.user_id
"""


async def list_users(
    cur: AsyncCursor,
    *,
    default_plan: str,
    query: str = "",
    plan: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    like = f"%{query.strip()}%" if query.strip() else "%"
    await cur.execute(
        f"""
        SELECT {_USER_COLS}
        {_USER_FROM}
        WHERE (u.user_id ILIKE %(like)s OR u.email ILIKE %(like)s
               OR u.name ILIKE %(like)s)
          AND (%(plan)s = '' OR COALESCE(up.plan_code, %(default_plan)s) = %(plan)s)
        ORDER BY u.created_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {
            "default_plan": default_plan,
            "like": like,
            "plan": plan.strip(),
            "limit": limit,
            "offset": offset,
        },
    )
    return await cur.fetchall()


async def count_users(
    cur: AsyncCursor, *, default_plan: str, query: str = "", plan: str = ""
) -> int:
    like = f"%{query.strip()}%" if query.strip() else "%"
    await cur.execute(
        f"""
        SELECT count(*) AS n
        {_USER_FROM}
        WHERE (u.user_id ILIKE %(like)s OR u.email ILIKE %(like)s
               OR u.name ILIKE %(like)s)
          AND (%(plan)s = '' OR COALESCE(up.plan_code, %(default_plan)s) = %(plan)s)
        """,
        {"default_plan": default_plan, "like": like, "plan": plan.strip()},
    )
    row = await cur.fetchone() or {}
    return int(row.get("n") or 0)


async def user_detail(cur: AsyncCursor, user_id: str, default_plan: str) -> Optional[dict]:
    await cur.execute(
        f"SELECT {_USER_COLS} {_USER_FROM} WHERE u.user_id = %(user_id)s",
        {"user_id": user_id, "default_plan": default_plan},
    )
    return await cur.fetchone()


async def recent_ledger(cur: AsyncCursor, user_id: str, limit: int = 20) -> list[dict]:
    await cur.execute(
        "SELECT id, delta, reason, source, source_id, created_at "
        "FROM billing.ledger WHERE user_id = %s "
        "ORDER BY created_at DESC LIMIT %s",
        (user_id, limit),
    )
    return await cur.fetchall()


async def active_leases(cur: AsyncCursor, user_id: str) -> list[dict]:
    await cur.execute(
        "SELECT run_ref, reserved_credits, generation, created_at, expires_at "
        "FROM billing.leases WHERE user_id = %s "
        "AND released_at IS NULL AND expires_at > now() "
        "ORDER BY created_at DESC",
        (user_id,),
    )
    return await cur.fetchall()


async def list_plans(cur: AsyncCursor) -> list[dict]:
    await cur.execute(
        "SELECT code, name, description, access_tier, scopes, limits, "
        "sandbox_pricing, monthly_credits, price_cny, included_hours_month "
        "FROM billing.plans ORDER BY access_tier, code"
    )
    return await cur.fetchall()


async def plan_exists(cur: AsyncCursor, code: str) -> bool:
    await cur.execute("SELECT 1 FROM billing.plans WHERE code = %s", (code,))
    return (await cur.fetchone()) is not None


async def plan_code_of(cur: AsyncCursor, user_id: str, default_plan: str) -> str:
    await cur.execute(
        "SELECT plan_code FROM billing.user_plans WHERE user_id = %s", (user_id,)
    )
    row = await cur.fetchone()
    return str(row["plan_code"]) if row else default_plan


async def dashboard_stats(cur: AsyncCursor, default_plan: str) -> dict:
    await cur.execute(
        """
        SELECT
          (SELECT count(*) FROM public.users) AS users,
          (SELECT count(*) FROM billing.user_plans) AS assigned,
          (SELECT count(*) FROM billing.wallets WHERE balance < 0) AS negative,
          (SELECT count(*) FROM billing.leases
             WHERE released_at IS NULL AND expires_at > now()) AS leases,
          (SELECT COALESCE(SUM(reserved_credits), 0) FROM billing.leases
             WHERE released_at IS NULL AND expires_at > now()) AS reserved
        """
    )
    row = await cur.fetchone() or {}
    await cur.execute(
        """
        SELECT COALESCE(up.plan_code, %s) AS plan_code, count(*) AS n
        FROM public.users u
        LEFT JOIN billing.user_plans up ON up.user_id = u.user_id
        GROUP BY 1 ORDER BY 2 DESC
        """,
        (default_plan,),
    )
    distribution = await cur.fetchall()
    return {**row, "distribution": distribution}


async def list_ledger(
    cur: AsyncCursor,
    *,
    user_id: str = "",
    reason: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    await cur.execute(
        """
        SELECT id, user_id, delta, reason, source, source_id, created_at
        FROM billing.ledger
        WHERE (%s = '' OR user_id = %s) AND (%s = '' OR reason = %s)
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """,
        (user_id, user_id, reason, reason, limit, offset),
    )
    return await cur.fetchall()


# ---------------------------------------------------------------------------
# Token usage (read from dsalpha's conversation_usages, never written here)
# ---------------------------------------------------------------------------

_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_tokens",
    "call_count",
)


async def token_usage_report(
    cur: AsyncCursor, user_id: str, days: int = 30
) -> dict:
    """Per-user token usage over the last ``days`` days.

    ``token_usage.by_model`` is keyed by model name and holds the counters
    dsalpha already priced; summing it keeps BYOK and platform calls
    together (``platform_cost`` is the part actually billed as credits).
    """
    await cur.execute(
        """
        SELECT
          m.key AS model,
          COALESCE(SUM((m.value->>'input_tokens')::bigint), 0)::bigint  AS input_tokens,
          COALESCE(SUM((m.value->>'output_tokens')::bigint), 0)::bigint AS output_tokens,
          COALESCE(SUM((m.value->>'total_tokens')::bigint), 0)::bigint  AS total_tokens,
          COALESCE(SUM((m.value->>'cached_tokens')::bigint), 0)::bigint AS cached_tokens,
          COALESCE(SUM((m.value->>'call_count')::bigint), 0)::bigint    AS call_count,
          COALESCE(SUM((m.value->>'total_cost')::float8), 0)            AS total_cost
        FROM public.conversation_usages u,
             jsonb_each(u.token_usage->'by_model') AS m
        WHERE u.user_id = %s
          AND u.created_at >= now() - make_interval(days => %s)
          AND jsonb_typeof(u.token_usage->'by_model') = 'object'
        GROUP BY m.key
        ORDER BY total_tokens DESC
        """,
        (user_id, days),
    )
    by_model = [
        {**dict(row), "total_cost": round(float(row["total_cost"] or 0), 6)}
        for row in await cur.fetchall()
    ]

    tokens = {
        field: sum(int(row[field] or 0) for row in by_model)
        for field in _TOKEN_FIELDS
    }
    total_cost = sum(float(row["total_cost"] or 0) for row in by_model)

    await cur.execute(
        """
        SELECT count(*) AS turns,
               count(*) FILTER (WHERE token_usage IS NOT NULL) AS turns_with_usage,
               COALESCE(SUM(token_credits), 0) AS token_credits,
               COALESCE(SUM(infrastructure_credits), 0) AS infrastructure_credits,
               COALESCE(SUM((token_usage->>'platform_cost')::float8), 0) AS platform_cost
        FROM public.conversation_usages
        WHERE user_id = %s
          AND created_at >= now() - make_interval(days => %s)
        """,
        (user_id, days),
    )
    totals = dict(await cur.fetchone() or {})

    await cur.execute(
        """
        WITH u AS (
            SELECT date_trunc('day', created_at)::date AS day,
                   token_usage, token_credits, infrastructure_credits
            FROM public.conversation_usages
            WHERE user_id = %s
              AND created_at >= now() - make_interval(days => %s)
        ), tk AS (
            SELECT u.day,
                   SUM((m.value->>'input_tokens')::bigint)  AS input_tokens,
                   SUM((m.value->>'output_tokens')::bigint) AS output_tokens,
                   SUM((m.value->>'total_tokens')::bigint)  AS total_tokens,
                   SUM((m.value->>'call_count')::bigint)    AS call_count
            FROM u, jsonb_each(u.token_usage->'by_model') AS m
            WHERE jsonb_typeof(u.token_usage->'by_model') = 'object'
            GROUP BY u.day
        )
        SELECT u.day,
               count(*) AS turns,
               COALESCE(SUM(u.token_credits), 0) AS token_credits,
               COALESCE(SUM(u.infrastructure_credits), 0) AS infrastructure_credits,
               COALESCE(MAX(tk.input_tokens), 0)::bigint  AS input_tokens,
               COALESCE(MAX(tk.output_tokens), 0)::bigint AS output_tokens,
               COALESCE(MAX(tk.total_tokens), 0)::bigint  AS total_tokens,
               COALESCE(MAX(tk.call_count), 0)::bigint    AS call_count
        FROM u LEFT JOIN tk ON tk.day = u.day
        GROUP BY u.day, tk.input_tokens, tk.output_tokens,
                 tk.total_tokens, tk.call_count
        ORDER BY u.day DESC
        """,
        (user_id, days),
    )
    by_day = [dict(row) for row in await cur.fetchall()]

    return {
        "days": days,
        "summary": {
            **tokens,
            "total_cost": round(total_cost, 6),
            "platform_cost": round(float(totals.get("platform_cost") or 0), 6),
            "turns": int(totals.get("turns") or 0),
            "turns_with_usage": int(totals.get("turns_with_usage") or 0),
            "token_credits": round(float(totals.get("token_credits") or 0), 6),
            "infrastructure_credits": round(
                float(totals.get("infrastructure_credits") or 0), 6
            ),
        },
        "by_model": by_model,
        "by_day": by_day,
    }


async def list_audit(cur: AsyncCursor, limit: int = 100, offset: int = 0) -> list[dict]:
    await cur.execute(
        "SELECT id, actor, action, target, detail, created_at "
        "FROM billing.admin_audit ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (limit, offset),
    )
    return await cur.fetchall()
