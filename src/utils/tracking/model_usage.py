"""Per-model token usage for Roost Console's ``release`` payload.

Console owns pricing, so dslpha only has to report *what ran*: input, output,
cache-read and cache-write tokens per model, with the call count. The sources
differ by age and by path:

* a live turn has the tracker's raw per-call records, whose ``usage`` dict
  carries the full LangChain token breakdown (including the cache write TTL
  split);
* a finalized turn has its persisted ``token_usage`` JSONB, whose
  ``per_call_costs`` keeps input/output/cached per call but not the cache write
  split (older rows), and whose ``by_model`` is a coarser fallback;
* BYOK calls are recorded but never charged, so the release must not include
  them — Console would price them like platform-funded tokens.

Component split matters for same-price parity with relay. LangChain's
``input_tokens`` is inclusive: it holds cache reads and cache writes as well as
regular prompt tokens. The relay reports the vendor's split, so this module
subtracts cache tokens back out — ``input`` here is regular input only, and
``cache_read`` / ``cache_write`` are their own components. Reporting the
inclusive figure would double-charge every cache hit at the input rate.

Rows written before the TTL split existed carry no cache-write count, and the
persisted ``per_call_costs`` never did. Those aggregate with
``cache_write = 0``, which is the shape the old billing used (cache writes were
priced inside input) and is therefore lossless for the historic rows: Console's
price book prices them at the input rate only if the model's cache_write price
is zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


def _count(value: Any) -> int:
    """A non-negative token count from provider-parsed JSON, or 0."""
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if parsed > 0 else 0


def _token_parts(usage: Mapping[str, Any]) -> Dict[str, int]:
    """Split one call's LangChain usage dict into Console's components."""
    raw_input = _count(usage.get("input_tokens"))
    cache_read = _count(usage.get("cached_tokens"))
    # Anthropic-style cache writes (5m + 1h) plus the doubao-style storage
    # count. They all land on the one cache_write component Console has.
    cache_write = (
        _count(usage.get("cache_5m_tokens"))
        + _count(usage.get("cache_1h_tokens"))
        + _count(usage.get("cache_storage_tokens"))
    )
    regular_input = max(0, raw_input - cache_read - cache_write)
    return {
        "input": regular_input,
        "output": _count(usage.get("output_tokens")),
        "cache_read": cache_read,
        "cache_write": cache_write,
    }


def _is_platform(record: Mapping[str, Any]) -> bool:
    return record.get("billing_type", "platform") == "platform"


@dataclass
class ModelUsage:
    model: str
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    calls: int = 0

    def add(self, parts: Mapping[str, int], calls: int = 1) -> None:
        for key in ("input", "output", "cache_read", "cache_write"):
            setattr(self, key, getattr(self, key) + int(parts.get(key, 0) or 0))
        self.calls += calls

    def as_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "calls": self.calls,
        }


@dataclass(frozen=True)
class ReleaseSettlement:
    """What the release reports about a turn's platform spend.

    ``model_usage`` is the authoritative figure for Console pricing; ``spent_usd``
    is the transitional fallback (and the only figure for a model the book does
    not list). ``byok`` says the turn ran on the user's own key: Console records
    the usage but must not debit for it.

    ``has_records`` distinguishes "no model calls at all" (settle nothing, or
    fall back to the ledger's in-flight figure) from "calls that priced to
    zero" — the difference matters because an empty ``model_usage`` must not be
    sent as "this turn used no tokens" when the tracker simply never saw it.
    """

    model_usage: List[Dict[str, Any]] = field(default_factory=list)
    spent_usd: Optional[float] = None
    byok: bool = False
    has_records: bool = False
    call_count: int = 0


def aggregate_model_usage(
    per_call_records: Sequence[Mapping[str, Any]], *, platform_only: bool = True
) -> List[Dict[str, Any]]:
    """Aggregate raw tracker records (``PerCallTokenTracker`` shape) by model."""
    models: Dict[str, ModelUsage] = {}
    for record in per_call_records:
        if platform_only and not _is_platform(record):
            continue
        model = record.get("model_name")
        if not isinstance(model, str) or not model:
            continue
        usage = record.get("usage")
        if not isinstance(usage, Mapping):
            continue
        entry = models.setdefault(model, ModelUsage(model=model))
        entry.add(_token_parts(usage))
    return [models[name].as_dict() for name in sorted(models)]


def aggregate_persisted_costs(
    per_call_costs: Iterable[Mapping[str, Any]], *, platform_only: bool = True
) -> List[Dict[str, Any]]:
    """Aggregate ``token_usage.per_call_costs`` rows by model.

    These rows keep the inclusive input count and the cache-read count only;
    the cache write split is not persisted, so it aggregates as zero.
    """
    models: Dict[str, ModelUsage] = {}
    for cost in per_call_costs:
        if not isinstance(cost, Mapping):
            continue
        if platform_only and not _is_platform(cost):
            continue
        model = cost.get("model_name")
        if not isinstance(model, str) or not model:
            continue
        raw_input = _count(cost.get("input_tokens"))
        cache_read = _count(cost.get("cached_tokens"))
        entry = models.setdefault(model, ModelUsage(model=model))
        entry.add(
            {
                "input": max(0, raw_input - cache_read),
                "output": _count(cost.get("output_tokens")),
                "cache_read": cache_read,
                "cache_write": 0,
            }
        )
    return [models[name].as_dict() for name in sorted(models)]


def by_model_fallback(token_usage: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Coarsest fallback: the persisted ``by_model`` aggregate.

    It has per-model call counts but no per-call billing split, so a turn that
    mixed platform and BYOK calls cannot be separated here. Only used when
    ``per_call_costs`` is absent, which is the pre-v2 row shape.
    """
    by_model = token_usage.get("by_model")
    if not isinstance(by_model, Mapping):
        return []
    models: Dict[str, ModelUsage] = {}
    for model, aggregate in by_model.items():
        if not isinstance(model, str) or not isinstance(aggregate, Mapping):
            continue
        raw_input = _count(aggregate.get("input_tokens"))
        cache_read = _count(aggregate.get("cached_tokens"))
        entry = models.setdefault(model, ModelUsage(model=model))
        entry.add(
            {
                "input": max(0, raw_input - cache_read),
                "output": _count(aggregate.get("output_tokens")),
                "cache_read": cache_read,
                "cache_write": 0,
            },
            calls=_count(aggregate.get("call_count")) or 1,
        )
    return [models[name].as_dict() for name in sorted(models)]


def model_usage_from_token_usage(
    token_usage: Mapping[str, Any], *, platform_only: bool = True
) -> List[Dict[str, Any]]:
    """Aggregate a persisted ``conversation_usages.token_usage`` payload."""
    if not isinstance(token_usage, Mapping):
        return []
    per_call = token_usage.get("per_call_costs")
    if isinstance(per_call, list) and per_call:
        return aggregate_persisted_costs(per_call, platform_only=platform_only)
    return by_model_fallback(token_usage)


def platform_usd_from_token_usage(token_usage: Mapping[str, Any]) -> Optional[float]:
    """The persisted platform USD figure, or None when the row predates it."""
    if not isinstance(token_usage, Mapping):
        return None
    value = token_usage.get("platform_cost")
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return max(parsed, 0.0)


def merge_model_usage(
    *groups: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Sum several model-usage lists (a turn family's lanes, or retries)."""
    models: Dict[str, ModelUsage] = {}
    for group in groups:
        for item in group or ():
            if not isinstance(item, Mapping):
                continue
            model = item.get("model")
            if not isinstance(model, str) or not model:
                continue
            entry = models.setdefault(model, ModelUsage(model=model))
            entry.input += _count(item.get("input"))
            entry.output += _count(item.get("output"))
            entry.cache_read += _count(item.get("cache_read"))
            entry.cache_write += _count(item.get("cache_write"))
            entry.calls += _count(item.get("calls"))
    return [models[name].as_dict() for name in sorted(models)]


def price_difference_ratio(
    charged_credits: Any, spent_usd: Any, usd_to_credits: Any
) -> Optional[float]:
    """How far a priced charge sits from the transitional USD estimate.

    None when either side is unavailable. Expressed against the priced charge
    (the figure that was actually debited), so a disagreement reads as a
    percentage of the money, not of an estimate that may itself be wrong.
    """
    charged = _number_float(charged_credits)
    spent = _number_float(spent_usd)
    rate = _number_float(usd_to_credits)
    if charged is None or spent is None or rate is None:
        return None
    estimate = spent * rate
    return abs(charged - estimate) / max(abs(charged), 1.0)


def _number_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


__all__ = [
    "ModelUsage",
    "ReleaseSettlement",
    "aggregate_model_usage",
    "aggregate_persisted_costs",
    "by_model_fallback",
    "merge_model_usage",
    "model_usage_from_token_usage",
    "platform_usd_from_token_usage",
    "price_difference_ratio",
]
