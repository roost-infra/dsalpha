"""Plan and quota arithmetic.

Pure functions only: no database, no FastAPI. This is the part the unit tests
pin down, because it is where a wrong answer becomes either an unjustified
refusal or an unbounded spend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

DEFAULT_PER_TURN_CREDITS = 500.0


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    access_tier: int
    scopes: tuple[str, ...]
    limits: Mapping[str, Any]
    sandbox_pricing: Mapping[str, Any]
    monthly_credits: float
    # Display/accounting only; money moves as credits.
    price_cny: float = 0.0
    included_hours_month: float = 0.0


def plan_from_row(row: Mapping[str, Any]) -> Plan:
    return Plan(
        code=str(row["code"]),
        name=str(row["name"]),
        access_tier=int(row.get("access_tier") or 0),
        scopes=tuple(row.get("scopes") or ()),
        limits=dict(row.get("limits") or {}),
        sandbox_pricing=dict(row.get("sandbox_pricing") or {}),
        monthly_credits=float(row.get("monthly_credits") or 0),
        price_cny=float(row.get("price_cny") or 0),
        included_hours_month=float(row.get("included_hours_month") or 0),
    )


def available_credits(balance: float, reserved: float) -> float:
    """What the user may still spend right now, in-flight reservations included."""
    return round(float(balance) - float(reserved), 6)


def limit_of(plan: Plan, *names: str) -> Optional[int]:
    """The first limit the plan names, or None (unlimited) when it names none.

    A negative value is the platform's "unlimited" too, matching what
    dsalpha's own quota readers accept.
    """
    for name in names:
        value = plan.limits.get(name)
        if value is not None:
            return int(value)
    return None


def within(used: int, limit: Optional[int]) -> bool:
    if limit is None or limit < 0:
        return True
    return used < limit


def per_turn_cap(plan: Plan, fallback: float = DEFAULT_PER_TURN_CREDITS) -> float:
    value = plan.limits.get("per_turn_credits")
    try:
        return float(value) if value is not None else float(fallback)
    except (TypeError, ValueError):
        return float(fallback)


def _capacity(used: int, limit: Optional[int], limit_type: str, label: str) -> dict:
    allowed = within(used, limit)
    return {
        "allowed": allowed,
        "message": None if allowed else f"{label} limit reached ({used}/{limit})",
        "limit_type": limit_type,
        "capacity_used": used,
        "capacity_limit": limit,
    }


def build_quota(
    *,
    check_quota: Optional[str],
    plan: Plan,
    balance: float,
    reserved: float,
    used_credits_month: float,
    counts: Mapping[str, int],
    byok: bool = False,
) -> dict:
    """The ``quota`` object dsalpha reads out of ``validate``.

    ``check_quota`` is one of the names dsalpha sends: ``chat``,
    ``computer_count``, ``workspace``, ``always_on`` or ``spec_<tier>``.
    Anything else (or None) only carries membership, so it always allows.
    """
    if check_quota == "chat":
        available = available_credits(balance, reserved)
        # A BYOK turn spends the user's own key, not platform credits; tool
        # credits are billed separately and do not gate the turn itself.
        # A negative balance is recorded as debt but always denies the next
        # turn, so a spending burst cannot compound indefinitely.
        allowed = True if byok else available > 0
        return {
            "allowed": allowed,
            "message": None if allowed else "Out of credits",
            "limit_type": "credit_limit",
            "credit_limit": plan.limits.get("credit_limit"),
            "used_credits": round(float(used_credits_month), 6),
            "remaining_credits": round(max(available, 0.0), 6),
            "outstanding_debt": round(max(-available, 0.0), 6),
            "retry_after": 30,
        }

    if check_quota == "computer_count":
        used = int(counts.get("computer_count", 0))
        limit = limit_of(plan, "computer_count")
        quota = _capacity(used, limit, "computer_limit", "computer")
        quota.update(
            active_computers=used,
            computer_limit=limit,
            active_workspaces=used,
            workspace_limit=limit,
        )
        return quota

    if check_quota == "workspace":
        used = int(counts.get("live_count", 0))
        limit = limit_of(plan, "concurrent_computers", "computer_count")
        quota = _capacity(used, limit, "workspace_limit", "workspace")
        quota.update(active_workspaces=used, workspace_limit=limit)
        return quota

    if check_quota == "always_on":
        used = int(counts.get("always_on", 0))
        limit = limit_of(plan, "always_on")
        return _capacity(used, limit, "always_on_limit", "always-on")

    if check_quota in ("spec_performance", "spec_max", "spec_xlarge"):
        # The platform counts every elevated tier against one slot, so a move
        # between them does not multiply the allowance.
        used = int(counts.get("spec_count", 0))
        limit = limit_of(plan, "spec_computers")
        return _capacity(used, limit, check_quota, "elevated spec")

    return {"allowed": True}
