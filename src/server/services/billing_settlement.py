"""Settle the runs whose release had no spend figure, from their usage rows.

The compatibility release settles a turn by naming what it spent. When that
figure cannot be read, retiring the lease anyway releases the whole reserved
ceiling and the console charges nothing — the turn is given away. The fix is a
queue, not a retry inline: finalize writes the run's ``conversation_usages``
row only after the gate has torn down, so the inline release cannot wait for it,
but a worker a couple of minutes later can read it.

Each pending run is settled with the same payload the inline release sends —
``model_usage`` aggregated from the persisted per-call records, ``spent_usd``
as the transitional fallback, ``byok`` for a turn that ran on the user's own
key. That keeps the console's pricing path identical for both, and the usage
row is exactly the record the inline release would have built from memory.

Idempotency is layered. The console's release is idempotent per run/generation,
and ``billing_settled_at`` is the local terminal stamp; a second worker
finding the same row loses the CAS. A retryable answer (402, 401/403/404,
429/5xx, network) leaves the run queued; an answer nothing can change (a
malformed payload, ``409`` for an already-released lease) stamps it settled
with the error so it leaves the queue, mirroring the sandbox reporter's rule.

The worker runs on every worker behind a session advisory lock; the console
covers any overlap that remains.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from src.config import billing_rates as rates_cache
from src.config.env import (
    BILLING_SETTLEMENT_GRACE_SECONDS,
    BILLING_SETTLEMENT_INTERVAL_SECONDS,
)
from src.config.settings import AUTH_SERVICE_URL
from src.server.database import session_lock
from src.server.database.runs import billing_settlement as settlement_db
from src.server.dependencies import usage_limits
from src.utils.tracking.model_usage import (
    model_usage_from_token_usage,
    platform_usd_from_token_usage,
)

logger = logging.getLogger(__name__)

RELEASE_PATH = "/api/auth/billing/leases/release"
_SETTLEMENT_LOCK = "billing_settlement:worker"
_ERROR_MAX = 500

# Same rule as the sandbox reporter: these recover on their own (a top-up, a
# fixed secret, a created organization, a throttled or down console). The rest
# of the 4xx range is the console rejecting the report itself — notably 409 for
# a lease it has already settled — which another attempt cannot change.
_RETRYABLE_4XX = frozenset({401, 402, 403, 404, 408, 425, 429})

# A charged amount this far from the transitional USD estimate is reported per
# run. The console now prices from the book (same as relay); the estimate is
# the old scalar path and is expected to disagree eventually, which is the
# signal that the fallback can be retired.
_DIFF_REPORT_RATIO = 0.05


@dataclass(frozen=True)
class ReleaseOutcome:
    """What happened to one pending run."""

    run_id: str
    status: str  # settled | retry | failed | skipped
    charged_credits: Optional[int] = None
    http_status: Optional[int] = None
    error: Optional[str] = None


@dataclass
class SettlementSweepResult:
    listed: int = 0
    settled: int = 0
    retried: int = 0
    failed: int = 0
    skipped: int = 0

    def add(self, outcome: ReleaseOutcome) -> None:
        if outcome.status == "settled":
            self.settled += 1
        elif outcome.status == "retry":
            self.retried += 1
        elif outcome.status == "failed":
            self.failed += 1
        else:
            self.skipped += 1


def _text(value: Any, limit: int = _ERROR_MAX) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text[:limit]


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def build_release_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """The console's release body for one pending run.

    Models are respelled to the fetched price book's own naming, because the
    manifest keys hyphens where the book (built from the relay config) uses the
    dotted vendor spelling; an unmatched name answers ``unknown_model`` and
    drops the turn onto the scalar fallback.
    """
    run_id = str(row["run_id"])
    token_usage = row.get("token_usage")
    model_usage = model_usage_from_token_usage(token_usage or {})
    for entry in model_usage:
        entry["model"] = rates_cache.console_model_name(entry["model"])
    spent_usd = platform_usd_from_token_usage(token_usage or {})

    payload: dict[str, Any] = {
        "user_id": str(row["user_id"]) if row.get("user_id") else "",
        "run_ref": run_id,
    }
    if model_usage:
        payload["model_usage"] = model_usage
    if spent_usd is not None:
        payload["spent_usd"] = round(spent_usd, 10)
    if row.get("is_byok"):
        payload["byok"] = True
    # Transitional legacy field: the old quota service settles from it, and the
    # console ignores it. Carries the run's full credits (tokens + infra) so
    # that path is unchanged.
    total_credits = _number(row.get("total_credits"))
    if total_credits is not None and total_credits > 0:
        payload["spent_credits"] = total_credits
    return payload


def _charged_credits(response: Any) -> Optional[int]:
    """The console's reported charge, when it names one."""
    try:
        body = response.json()
    except Exception:
        return None
    if not isinstance(body, Mapping):
        return None
    value = body.get("charged_credits")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _response_body(response: Any) -> Mapping[str, Any]:
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, Mapping) else {}


def _log_price_difference(run_id: str, response: Any, spent_usd: Optional[float]) -> None:
    """Report a priced charge that disagrees with the transitional estimate."""
    body = _response_body(response)
    charged = _charged_credits(response)
    if body.get("fallback") is True:
        logger.warning(
            "[Billing] settlement of run %s fell back to the spent_usd path "
            "(a model was not in the price book); the turn is priced at the "
            "scalar rate, not the book",
            run_id,
        )
    if charged is None or spent_usd is None:
        return
    estimate = spent_usd * rates_cache.usd_to_credits_rate()
    denominator = max(abs(charged), 1.0)
    ratio = abs(charged - estimate) / denominator
    if ratio > _DIFF_REPORT_RATIO:
        logger.warning(
            "[Billing] model_usage charge for run %s is %d credits, %.1f%% off "
            "the spent_usd estimate %.2f — the two pricing paths disagree",
            run_id,
            charged,
            ratio * 100.0,
            estimate,
        )


async def _post(client: Any, payload: Mapping[str, Any]) -> Any:
    url = f"{AUTH_SERVICE_URL.rstrip('/')}{RELEASE_PATH}"
    raw = json.dumps(payload, separators=(",", ":")).encode()
    headers = usage_limits.signed_service_headers(
        "POST", urlsplit(url).path, raw
    )
    headers["Content-Type"] = "application/json"
    return await client.post(url, content=raw, headers=headers)


def _retryable_status(status: int) -> bool:
    return status >= 500 or status in _RETRYABLE_4XX


async def settle_pending_run(
    row: Mapping[str, Any],
    *,
    client: Any,
) -> ReleaseOutcome:
    """Settle one pending run from its usage row.

    ``row`` is one entry from :func:`settlement_db.list_settle_pending`.
    """
    run_id = str(row["run_id"])
    if not row.get("user_id"):
        message = "run has no user/org principal; the console cannot bill it"
        await settlement_db.mark_settled(run_id, detail=message)
        logger.error("[Billing] pending run %s: %s", run_id, message)
        return ReleaseOutcome(run_id, "failed", error=message)

    payload = build_release_payload(row)
    if "model_usage" not in payload and "spent_usd" not in payload:
        message = "usage row carries neither model_usage nor spent_usd"
        await settlement_db.mark_settled(run_id, detail=message)
        logger.error(
            "[Billing] pending run %s has no settleable spend figure; leaving "
            "the queue so it is visible rather than retried forever",
            run_id,
        )
        return ReleaseOutcome(run_id, "failed", error=message)

    try:
        response = await _post(client, payload)
    except Exception as e:
        message = f"release unreachable: {type(e).__name__}: {e}"
        await settlement_db.mark_settle_error(run_id, message)
        logger.warning("[Billing] pending run %s will retry: %s", run_id, message)
        return ReleaseOutcome(run_id, "retry", error=message)

    status = int(getattr(response, "status_code", 0))
    if 200 <= status < 300:
        charged = _charged_credits(response)
        _log_price_difference(run_id, response, platform_usd_from_token_usage(row.get("token_usage") or {}))
        await settlement_db.mark_settled(
            run_id, charged_credits=charged, detail="settled"
        )
        logger.info(
            "[Billing] settled pending run %s%s (HTTP %d)",
            run_id,
            f": {charged} credits" if charged is not None else "",
            status,
        )
        return ReleaseOutcome(
            run_id, "settled", charged_credits=charged, http_status=status
        )

    detail = _text(getattr(response, "text", "") or "")
    message = f"release HTTP {status}: {detail}"
    if _retryable_status(status):
        await settlement_db.mark_settle_error(run_id, message)
        logger.warning(
            "[Billing] pending run %s not settled yet; will retry (HTTP %d): %s",
            run_id,
            status,
            detail,
        )
        return ReleaseOutcome(
            run_id, "retry", http_status=status, error=message
        )

    # A refusal another attempt cannot change (409 already released, 400
    # malformed, 422 unknown model). Stamp it so it leaves the queue with the
    # reason an operator can read.
    await settlement_db.mark_settled(run_id, detail=message)
    logger.error(
        "[Billing] pending run %s refused permanently (HTTP %d): %s",
        run_id,
        status,
        detail,
    )
    return ReleaseOutcome(run_id, "failed", http_status=status, error=message)


async def settle_pending_runs(
    limit: int = 100,
    *,
    client: Any = None,
    grace_seconds: Optional[int] = None,
) -> SettlementSweepResult:
    """Settle up to ``limit`` pending runs, oldest first."""
    result = SettlementSweepResult()
    if not AUTH_SERVICE_URL:
        logger.debug("[Billing] settlement skipped: AUTH_SERVICE_URL is not set")
        return result
    if client is None and usage_limits.service_token_missing():
        logger.error(
            "[Billing] settlement skipped: INTERNAL_SERVICE_TOKEN is not set, "
            "so the console cannot authenticate this deployment"
        )
        return result
    http = client or await usage_limits.get_http_client()
    grace = (
        BILLING_SETTLEMENT_GRACE_SECONDS
        if grace_seconds is None
        else int(grace_seconds)
    )
    rows = await settlement_db.list_settle_pending(limit=limit, grace_seconds=grace)
    result.listed = len(rows)
    for row in rows:
        try:
            outcome = await settle_pending_run(row, client=http)
        except Exception as e:
            # One malformed row must not stop the sweep; the row stays queued
            # unless the failure already stamped it.
            logger.exception(
                "[Billing] settlement failed for run %s: %s", row.get("run_id"), e
            )
            result.failed += 1
            continue
        result.add(outcome)

    if result.settled or result.retried or result.failed:
        logger.info(
            "[Billing] settlement: %d settled, %d retrying, %d failed of %d due",
            result.settled,
            result.retried,
            result.failed,
            result.listed,
        )
    orphaned = await settlement_db.count_pending_without_usage()
    if orphaned:
        logger.error(
            "[Billing] %d runs have been pending settlement for over an hour "
            "with no usage row to settle from; their finalize never committed",
            orphaned,
        )
    return result


class BillingSettlementWorker:
    """The per-worker loop that drains the pending-settlement queue.

    Same shape as the sandbox reporter: a session lock admits one worker per
    cycle, the loop never raises into startup, and the first cycle runs at
    once — the backlog from a deploy is exactly the runs whose inline release
    could not settle.
    """

    _instance: Optional["BillingSettlementWorker"] = None

    def __init__(
        self,
        interval_seconds: Optional[float] = None,
        limit: int = 100,
    ) -> None:
        self.interval_seconds = (
            float(interval_seconds)
            if interval_seconds is not None
            else float(BILLING_SETTLEMENT_INTERVAL_SECONDS)
        )
        self.limit = limit
        self._task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "BillingSettlementWorker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="billing-settlement")
        logger.info(
            "[Billing] settlement worker started (interval %ss)", self.interval_seconds
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        while True:
            try:
                if not usage_limits.platform_gating_active():
                    logger.info(
                        "[Billing] settlement worker idle: platform gating is inactive"
                    )
                    return
                async with session_lock.try_own_session_lock(
                    _SETTLEMENT_LOCK
                ) as held:
                    if held:
                        # The release payload respells models to the book and
                        # the difference report uses the live fx, so a worker
                        # that just booted fetches before its first cycle.
                        from src.server.services.billing_rates import (
                            ensure_console_rates,
                        )

                        await ensure_console_rates()
                        await settle_pending_runs(limit=self.limit)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "[Billing] settlement cycle failed: %s: %s", type(e).__name__, e
                )
            await asyncio.sleep(self.interval_seconds)


__all__ = [
    "BillingSettlementWorker",
    "ReleaseOutcome",
    "SettlementSweepResult",
    "build_release_payload",
    "settle_pending_run",
    "settle_pending_runs",
]
