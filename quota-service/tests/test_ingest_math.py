"""Sandbox pricing arithmetic used by the ingestion job."""

from quota_service.ingest import price_for_tier, sandbox_credits
from quota_service.quota import Plan


def plan(pricing=None) -> Plan:
    return Plan(
        code="t",
        name="Test",
        access_tier=0,
        scopes=(),
        limits={},
        sandbox_pricing=pricing or {},
        monthly_credits=0,
    )


def test_sandbox_credits_per_second():
    assert sandbox_credits(3600, 166.7) == 166.7
    assert sandbox_credits(1800, 100) == 50.0
    assert sandbox_credits(60, 0) == 0.0
    assert sandbox_credits(0, 100) == 0.0
    assert sandbox_credits(-5, 100) == 0.0


def test_price_for_tier_and_fallbacks():
    assert price_for_tier(plan({"performance": 333.3}), "performance", 1) == 333.3
    assert price_for_tier(plan({"standard": 166.7}), "performance", 99) == 99
    assert price_for_tier(plan({"default": 10}), "max", 99) == 10
    assert price_for_tier(plan(), "max", 99) == 99
    assert price_for_tier(plan({"max": "bad"}), "max", 99) == 99
