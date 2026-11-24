"""The release payload's model aggregation.

The figure this produces is what the console prices, so the cases that matter
are the ones where a naive aggregate is wrong: cache tokens are included in
LangChain's input count, BYOK calls must never appear (they are not the
platform's to bill), and the persisted row shape has less detail than the live
tracker's records.
"""

from __future__ import annotations

import pytest

from src.utils.tracking.model_usage import (
    ReleaseSettlement,
    aggregate_model_usage,
    aggregate_persisted_costs,
    by_model_fallback,
    merge_model_usage,
    model_usage_from_token_usage,
    platform_usd_from_token_usage,
    price_difference_ratio,
)


def record(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached: int = 0,
    cache_5m: int = 0,
    cache_1h: int = 0,
    billing_type: str = "platform",
) -> dict:
    return {
        "model_name": model,
        "billing_type": billing_type,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached,
            "cache_5m_tokens": cache_5m,
            "cache_1h_tokens": cache_1h,
        },
    }


# -- live tracker records ---------------------------------------------------


def test_calls_aggregate_per_model_in_a_stable_order():
    usage = aggregate_model_usage(
        [
            record("b-model", input_tokens=10, output_tokens=1),
            record("a-model", input_tokens=20, output_tokens=2),
            record("a-model", input_tokens=30, output_tokens=3),
        ]
    )
    assert [entry["model"] for entry in usage] == ["a-model", "b-model"]
    assert usage[0] == {
        "model": "a-model",
        "input": 50,
        "output": 5,
        "cache_read": 0,
        "cache_write": 0,
        "calls": 2,
    }


def test_cache_tokens_are_their_own_components_not_extra_input():
    """LangChain's input_tokens includes cache reads and writes. Reporting the
    inclusive figure would charge a cache hit at the full input rate on top of
    its cache-read price."""
    usage = aggregate_model_usage(
        [
            record(
                "m",
                input_tokens=1_000,
                output_tokens=10,
                cached=600,
                cache_5m=100,
                cache_1h=50,
            )
        ]
    )
    assert usage == [
        {
            "model": "m",
            "input": 250,
            "output": 10,
            "cache_read": 600,
            "cache_write": 150,
            "calls": 1,
        }
    ]


def test_byok_calls_are_not_platform_usage():
    usage = aggregate_model_usage(
        [
            record("m", input_tokens=100),
            record("own-key", input_tokens=999, billing_type="byok"),
        ]
    )
    assert [entry["model"] for entry in usage] == ["m"]
    assert usage[0]["input"] == 100

    everything = aggregate_model_usage(
        [record("own-key", input_tokens=1, billing_type="byok")],
        platform_only=False,
    )
    assert everything[0]["input"] == 1


def test_missing_or_unusable_fields_aggregate_as_zero():
    usage = aggregate_model_usage(
        [
            {"model_name": "m", "usage": {"input_tokens": "not-a-number",
                                          "output_tokens": -5}},
            {"model_name": None, "usage": {"input_tokens": 5}},
            {"usage": {"input_tokens": 5}},
        ]
    )
    assert usage == [
        {
            "model": "m",
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
            "calls": 1,
        }
    ]


# -- persisted token_usage --------------------------------------------------


def test_persisted_costs_keep_the_component_split_they_have():
    usage = aggregate_persisted_costs(
        [
            {
                "model_name": "m",
                "input_tokens": 10_000,
                "output_tokens": 100,
                "cached_tokens": 4_000,
                "billing_type": "platform",
            },
            {
                "model_name": "own-key",
                "input_tokens": 50,
                "output_tokens": 5,
                "billing_type": "byok",
            },
        ]
    )
    assert usage == [
        {
            "model": "m",
            "input": 6_000,
            "output": 100,
            "cache_read": 4_000,
            "cache_write": 0,
            "calls": 1,
        }
    ]


def test_model_usage_prefers_per_call_rows_over_the_coarse_aggregate():
    token_usage = {
        "per_call_costs": [
            {
                "model_name": "m",
                "input_tokens": 100,
                "output_tokens": 10,
                "cached_tokens": 0,
                "billing_type": "platform",
            }
        ],
        "by_model": {
            "m": {"input_tokens": 999, "output_tokens": 99, "call_count": 9}
        },
    }
    assert model_usage_from_token_usage(token_usage)[0]["input"] == 100


def test_a_row_without_per_call_costs_falls_back_to_by_model():
    token_usage = {
        "by_model": {
            "m": {
                "input_tokens": 1_000,
                "output_tokens": 100,
                "cached_tokens": 200,
                "call_count": 3,
            }
        }
    }
    usage = model_usage_from_token_usage(token_usage)
    assert usage == [
        {
            "model": "m",
            "input": 800,
            "output": 100,
            "cache_read": 200,
            "cache_write": 0,
            "calls": 3,
        }
    ]


def test_an_empty_or_unreadable_payload_aggregates_to_nothing():
    assert model_usage_from_token_usage({}) == []
    assert model_usage_from_token_usage(None) == []
    assert by_model_fallback({"by_model": "not-a-dict"}) == []


def test_platform_usd_reads_only_a_finite_non_negative_figure():
    assert platform_usd_from_token_usage({"platform_cost": 0.0123}) == 0.0123
    assert platform_usd_from_token_usage({"platform_cost": -1}) == 0.0
    assert platform_usd_from_token_usage({"platform_cost": "nan"}) is None
    assert platform_usd_from_token_usage({"platform_cost": True}) is None
    assert platform_usd_from_token_usage({}) is None


# -- merging and comparison -------------------------------------------------


def test_merging_sums_the_same_model_across_lists():
    merged = merge_model_usage(
        [{"model": "m", "input": 10, "output": 1, "calls": 1}],
        [{"model": "m", "input": 5, "cache_read": 2, "calls": 2}],
    )
    assert merged == [
        {
            "model": "m",
            "input": 15,
            "output": 1,
            "cache_read": 2,
            "cache_write": 0,
            "calls": 3,
        }
    ]


def test_the_settlement_defaults_to_nothing_reported():
    settlement = ReleaseSettlement()
    assert settlement.has_records is False
    assert settlement.model_usage == []
    assert settlement.spent_usd is None


@pytest.mark.parametrize(
    "charged, spent, rate",
    [(None, 1.0, 720), (8.9, None, 720), (8.9, 0.0123, None), (True, 1.0, 720)],
)
def test_price_difference_ratio_needs_both_figures(charged, spent, rate):
    assert price_difference_ratio(charged, spent, rate) is None


def test_price_difference_ratio_is_against_the_charged_figure():
    assert price_difference_ratio(100, 1.0, 110) == pytest.approx(0.1)
    assert price_difference_ratio(0, 0.0, 720) == 0.0


# -- minor conversion and the priced comparison ----------------------------


@pytest.mark.parametrize(
    "credits, expected",
    [
        (0, 0),
        (0.001, 1),
        (0.0004, 0),
        (0.5, 500),
        (1, 1000),
        (1.2345, 1235),
        (None, None),
        (-2, 0),
        ("nan", None),
        (True, None),
    ],
)
def test_credits_convert_to_integer_minor(credits, expected):
    from src.utils.tracking.model_usage import credits_to_minor

    assert credits_to_minor(credits) == expected


def test_the_surcharge_is_part_of_the_estimate_it_is_compared_with():
    from src.utils.tracking.model_usage import credits_to_minor

    # token estimate 1.0 USD × 720 = 720 credits; 280 credits of infrastructure
    # makes 1000 — matching the console's charge, so no disagreement.
    assert price_difference_ratio(1000, 1.0, 720, extra_credits=280) == 0.0
    assert credits_to_minor(280) == 280_000


def test_a_settlement_with_only_infrastructure_is_still_a_settlement():
    settlement = ReleaseSettlement(spent_usd=0.0, infra_credits=0.25)
    assert settlement.has_records is False
    assert settlement.infra_credits == 0.25
