"""Quota arithmetic: the part that decides allow/deny before any I/O."""

from quota_service.quota import Plan, available_credits, build_quota, per_turn_cap


def plan(limits=None) -> Plan:
    return Plan(
        code="t",
        name="Test",
        access_tier=1,
        scopes=(),
        limits=limits or {},
        sandbox_pricing={},
        monthly_credits=0,
    )


def test_available_subtracts_reservations():
    assert available_credits(100, 30) == 70
    assert available_credits(0, 0) == 0
    assert available_credits(-5, 0) == -5


def test_chat_allows_when_positive_and_denies_at_zero():
    allowed = build_quota(
        check_quota="chat",
        plan=plan(),
        balance=10,
        reserved=0,
        used_credits_month=0,
        counts={},
    )
    assert allowed["allowed"] is True
    assert allowed["remaining_credits"] == 10

    denied = build_quota(
        check_quota="chat",
        plan=plan(),
        balance=10,
        reserved=10,
        used_credits_month=0,
        counts={},
    )
    assert denied["allowed"] is False
    assert denied["limit_type"] == "credit_limit"
    assert denied["remaining_credits"] == 0

    negative = build_quota(
        check_quota="chat",
        plan=plan(),
        balance=-3,
        reserved=0,
        used_credits_month=3,
        counts={},
    )
    assert negative["allowed"] is False
    assert negative["outstanding_debt"] == 3


def test_chat_byok_does_not_need_platform_credits():
    quota = build_quota(
        check_quota="chat",
        plan=plan(),
        balance=0,
        reserved=0,
        used_credits_month=0,
        counts={},
        byok=True,
    )
    assert quota["allowed"] is True


def test_computer_count_limit_and_unlimited():
    quota = build_quota(
        check_quota="computer_count",
        plan=plan({"computer_count": 2}),
        balance=0,
        reserved=0,
        used_credits_month=0,
        counts={"computer_count": 1},
    )
    assert quota["allowed"] is True
    assert quota["capacity_limit"] == 2

    full = build_quota(
        check_quota="computer_count",
        plan=plan({"computer_count": 2}),
        balance=0,
        reserved=0,
        used_credits_month=0,
        counts={"computer_count": 2},
    )
    assert full["allowed"] is False
    assert full["limit_type"] == "computer_limit"

    unlimited = build_quota(
        check_quota="computer_count",
        plan=plan({"computer_count": -1}),
        balance=0,
        reserved=0,
        used_credits_month=0,
        counts={"computer_count": 999},
    )
    assert unlimited["allowed"] is True


def test_workspace_uses_live_count():
    quota = build_quota(
        check_quota="workspace",
        plan=plan({"computer_count": 5, "concurrent_computers": 2}),
        balance=0,
        reserved=0,
        used_credits_month=0,
        counts={"live_count": 2},
    )
    assert quota["allowed"] is False
    assert quota["workspace_limit"] == 2


def test_elevated_specs_share_one_slot():
    plan_with_one = plan({"spec_computers": 1})
    for used, expected in ((0, True), (1, False), (2, False)):
        quota = build_quota(
            check_quota="spec_max",
            plan=plan_with_one,
            balance=0,
            reserved=0,
            used_credits_month=0,
            counts={"spec_count": used},
        )
        assert quota["allowed"] is expected


def test_per_turn_cap_falls_back():
    assert per_turn_cap(plan({"per_turn_credits": 50}), 500) == 50
    assert per_turn_cap(plan(), 500) == 500
    assert per_turn_cap(plan({"per_turn_credits": "bad"}), 500) == 500


def test_unknown_check_only_allows():
    quota = build_quota(
        check_quota=None,
        plan=plan(),
        balance=0,
        reserved=0,
        used_credits_month=0,
        counts={},
    )
    assert quota == {"allowed": True}
