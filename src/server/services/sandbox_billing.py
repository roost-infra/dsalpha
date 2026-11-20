"""Report closed Daytona sandbox runs to Roost Console for billing.

Roost prices a sandbox from Daytona's list rates, marked up for Roost and
converted from USD to credits. Each closed ``computer_runs`` row is one
report: the configured resources it ran with, the interval it was up, and the
credits those come to. The console debits the organization's wallet under an
idempotency key, so a retry after a lost answer is a replay and not a second
charge.

A run is settled once. ``report_closed_runs`` claims the closed, unreported
runs and posts each, then records the outcome in the run's billing columns
(migration 118). The interesting cases are the answers that are not a simple
yes: 402 means the wallet is empty and the run stays queued for later, while
401/403/404 are configuration or account states that also resolve later and
must not poison a run. A malformed report the console will always refuse, or a
run with nothing billable in it, is marked settled with an error so it leaves
the queue.

Two billing limits are deliberate, and read as under-billing rather than bugs:

* Only the interval spent running is billed. A stopped sandbox keeps its disk
  until it is deleted; ``computer_runs`` has no disk-only or paused interval,
  so that storage is not charged yet.
* There is no historical backfill. Only runs closed after the columns existed
  are in the queue.

The caller is the reporter loop in the server's startup (one cycle per
``SANDBOX_BILLING_INTERVAL_SECONDS``). A session lock keeps one worker per
cycle on it; the console's idempotency key covers the rest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from src.config.env import (
    DAYTONA_CPU_USD_PER_HOUR,
    DAYTONA_DISK_FREE_GIB,
    DAYTONA_DISK_USD_PER_GIB_HOUR,
    DAYTONA_MEMORY_USD_PER_GIB_HOUR,
    SANDBOX_BILLING_INTERVAL_SECONDS,
    SANDBOX_MARKUP_BPS,
    USD_TO_CREDITS_RATE,
)
from src.config.settings import AUTH_SERVICE_URL
from src.server.database import computer_runs as runs_db
from src.server.database.session_lock import try_own_session_lock
from src.server.dependencies import usage_limits

logger = logging.getLogger(__name__)

# The console's product key for this deployment, and the prefix of its
# idempotency keys. Both are part of the console contract, not tuning knobs.
PRODUCT = "dsalpha"
PROVIDER = "daytona"
_IDEMPOTENCY_PREFIX = "dsalpha:computer_run:"
_REPORTER_LOCK = "sandbox_billing:reporter"

RESOLVE_ORG_PATH = "/internal/v1/orgs/resolve-user"
REPORT_SANDBOX_PATH = "/internal/v1/usage/sandbox"

# A component the console refuses for being out of range would be a metering
# bug; keeping the text lets an operator see why a run was left unsettled.
_ERROR_MAX = 500

# 402 is the documented "retry after a top-up". 401/403/404 are answered by
# fixing a secret, a scope or the user's organization, so retrying them is how
# a run is billed once the console is correct. The rest of the 4xx range is a
# malformed or impossible report, which another attempt cannot change.
_RETRYABLE_4XX = frozenset({401, 402, 403, 404, 408, 425, 429})


class BillingError(Exception):
    """A billing call failed before an answer could be used.

    ``status_code`` is the console's status when there was one, and None for a
    transport failure or an unreadable body.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class SandboxPrices:
    """The rates a charge is computed from.

    Separate from the environment so a test (or a future product) can price one
    charge without changing the process's configuration.
    """

    cpu_usd_per_hour: float = DAYTONA_CPU_USD_PER_HOUR
    memory_usd_per_gib_hour: float = DAYTONA_MEMORY_USD_PER_GIB_HOUR
    disk_usd_per_gib_hour: float = DAYTONA_DISK_USD_PER_GIB_HOUR
    disk_free_gib: float = DAYTONA_DISK_FREE_GIB


@dataclass(frozen=True)
class SandboxCharge:
    """One run's billable interval, broken into the console's components."""

    billable_seconds: int
    cpu_seconds: int
    memory_mib_seconds: int
    disk_mib_seconds: int
    gpu_seconds: int
    cpu_credits: float
    memory_credits: float
    disk_credits: float
    gpu_credits: float
    total_credits: int
    cpu_cores: float
    memory_gb: float
    disk_gb: float
    disk_billable_gb: float
    hours: float


@dataclass(frozen=True)
class BillingOutcome:
    """What happened to one run. ``status`` is reported/retry/failed/skipped."""

    run_id: str
    status: str
    total_credits: int = 0
    http_status: Optional[int] = None
    error: Optional[str] = None


@dataclass
class BillingSweepResult:
    """One cycle's counts, for the reporter's log line."""

    listed: int = 0
    reported: int = 0
    retried: int = 0
    failed: int = 0
    skipped: int = 0

    def add(self, outcome: BillingOutcome) -> None:
        if outcome.status == "reported":
            self.reported += 1
        elif outcome.status == "retry":
            self.retried += 1
        elif outcome.status == "failed":
            self.failed += 1
        else:
            self.skipped += 1


def idempotency_key(run_id: str) -> str:
    """The console's key for a run. A retry must reuse it exactly."""
    return f"{_IDEMPOTENCY_PREFIX}{run_id}"


def _number(name: str, value: Any) -> Decimal:
    """A non-negative finite figure, or ValueError.

    The caller marks the run instead of sending a number it does not believe;
    the console validates too, but a rejected report is a lost cycle.
    """
    try:
        parsed = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name} is not a number: {value!r}") from e
    if not math.isfinite(parsed):
        raise ValueError(f"{name} is not finite: {value!r}")
    if parsed < 0:
        raise ValueError(f"{name} is negative: {value!r}")
    return Decimal(str(parsed))


def _credits(value: Decimal) -> float:
    """A component credit as the console stores it: numeric(14,4)."""
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def compute_charge(
    cpu: float,
    memory_gb: float,
    disk_gb: float,
    seconds: float,
    markup_bps: int = SANDBOX_MARKUP_BPS,
    usd_to_credits: float = USD_TO_CREDITS_RATE,
    *,
    prices: Optional[SandboxPrices] = None,
) -> SandboxCharge:
    """Price one sandbox interval from its configured resources.

    ``hours`` follows the whole billable seconds reported, so the body's
    seconds and its credits describe the same interval. The first
    ``disk_free_gib`` GiB of disk are free, matching Daytona. Components are
    rounded to four decimals for the wire; the total is the ceiling of their
    unrounded sum, and at least one credit whenever anything was used.

    The ``*_seconds`` fields report the provisioned resource for the whole
    interval. Only ``disk_credits`` applies the free allowance, so
    ``disk_mib_seconds`` is not the billed disk quantity.
    """
    rates = prices or SandboxPrices()
    cpu_d = _number("cpu", cpu)
    memory_d = _number("memory_gb", memory_gb)
    disk_d = _number("disk_gb", disk_gb)
    seconds_d = _number("seconds", seconds)
    markup = Decimal(str(_number("markup_bps", markup_bps))) / Decimal(10000)
    usd_rate = Decimal(str(_number("usd_to_credits", usd_to_credits)))

    # Whole seconds are the console's unit; a sub-second tail rounds to the
    # nearest one, but a non-zero interval never becomes a zero-second one.
    billable_seconds = int(seconds_d.to_integral_value(rounding=ROUND_HALF_UP))
    if seconds_d > 0 and billable_seconds == 0:
        billable_seconds = 1
    hours = Decimal(billable_seconds) / Decimal(3600)

    cpu_credits = (
        cpu_d
        * hours
        * Decimal(str(_number("cpu_usd_per_hour", rates.cpu_usd_per_hour)))
        * usd_rate
        * markup
    )
    memory_credits = (
        memory_d
        * hours
        * Decimal(
            str(_number("memory_usd_per_gib_hour", rates.memory_usd_per_gib_hour))
        )
        * usd_rate
        * markup
    )
    disk_billable = max(
        disk_d - Decimal(str(_number("disk_free_gib", rates.disk_free_gib))), Decimal(0)
    )
    disk_credits = (
        disk_billable
        * hours
        * Decimal(str(_number("disk_usd_per_gib_hour", rates.disk_usd_per_gib_hour)))
        * usd_rate
        * markup
    )
    # Daytona does not price a GPU on the runs this deployment creates; the
    # component is sent as zero so the console's column is explicit.
    gpu_credits = Decimal(0)

    total = cpu_credits + memory_credits + disk_credits + gpu_credits
    used = billable_seconds > 0 and (cpu_d > 0 or memory_d > 0 or disk_d > 0)
    total_credits = int(total.to_integral_value(rounding=ROUND_CEILING)) if used else 0
    if used:
        total_credits = max(total_credits, 1)

    return SandboxCharge(
        billable_seconds=billable_seconds,
        cpu_seconds=int(
            (cpu_d * billable_seconds).to_integral_value(rounding=ROUND_HALF_UP)
        ),
        memory_mib_seconds=int(
            (memory_d * 1024 * billable_seconds).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        ),
        disk_mib_seconds=int(
            (disk_d * 1024 * billable_seconds).to_integral_value(rounding=ROUND_HALF_UP)
        ),
        gpu_seconds=0,
        cpu_credits=_credits(cpu_credits),
        memory_credits=_credits(memory_credits),
        disk_credits=_credits(disk_credits),
        gpu_credits=0.0,
        total_credits=total_credits,
        cpu_cores=float(cpu_d),
        memory_gb=float(memory_d),
        disk_gb=float(disk_d),
        disk_billable_gb=float(disk_billable),
        hours=float(hours),
    )


def unit_price_snapshot(
    prices: SandboxPrices,
    markup_bps: int,
    usd_to_credits: float,
) -> dict[str, Any]:
    """The rate card behind a charge, kept by the console for display.

    The effective per-hour prices are included because the list rates alone do
    not say what the wallet was charged; they are credits, after markup and the
    USD conversion.
    """
    markup = markup_bps / 10000
    return {
        "currency": "CNY",
        "usd_to_credits": usd_to_credits,
        "markup_bps": markup_bps,
        "cpu_usd_per_hour": prices.cpu_usd_per_hour,
        "memory_usd_per_gib_hour": prices.memory_usd_per_gib_hour,
        "disk_usd_per_gib_hour": prices.disk_usd_per_gib_hour,
        "disk_free_gib": prices.disk_free_gib,
        "cpu_credits_per_core_hour": round(
            prices.cpu_usd_per_hour * usd_to_credits * markup, 6
        ),
        "memory_credits_per_gib_hour": round(
            prices.memory_usd_per_gib_hour * usd_to_credits * markup, 6
        ),
        "disk_credits_per_billable_gib_hour": round(
            prices.disk_usd_per_gib_hour * usd_to_credits * markup, 6
        ),
    }


def _iso(value: Any) -> str:
    """RFC 3339 for the console, which decodes into a Go ``time.Time``."""
    if not isinstance(value, datetime):
        raise ValueError(f"not a timestamp: {value!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_usage_body(
    run: Mapping[str, Any],
    org_id: str,
    charge: SandboxCharge,
    *,
    prices: Optional[SandboxPrices] = None,
    markup_bps: int = SANDBOX_MARKUP_BPS,
    usd_to_credits: float = USD_TO_CREDITS_RATE,
) -> dict[str, Any]:
    """The console's sandbox-usage body for one run.

    ``sandbox_id`` is the logical sandbox -- the computer, which survives a
    provider sandbox being replaced -- while ``provider_sandbox_id`` names the
    Daytona sandbox the interval actually ran on.
    """
    rates = prices or SandboxPrices()
    run_id = str(run["run_id"])
    return {
        "org_id": org_id,
        "user_id": str(run["user_id"]),
        "product": PRODUCT,
        "sandbox_id": str(run["computer_id"]),
        "provider": PROVIDER,
        "provider_sandbox_id": str(run["provider_sandbox_id"]),
        "run_id": run_id,
        "started_at": _iso(run["started_at"]),
        "ended_at": _iso(run["ended_at"]),
        "billable_seconds": charge.billable_seconds,
        "cpu_seconds": charge.cpu_seconds,
        "memory_mib_seconds": charge.memory_mib_seconds,
        "disk_mib_seconds": charge.disk_mib_seconds,
        "gpu_seconds": charge.gpu_seconds,
        "cpu_credits": charge.cpu_credits,
        "memory_credits": charge.memory_credits,
        "disk_credits": charge.disk_credits,
        "gpu_credits": charge.gpu_credits,
        "total_credits": charge.total_credits,
        "unit_prices": unit_price_snapshot(rates, markup_bps, usd_to_credits),
        "currency": "CNY",
        "idempotency_key": idempotency_key(run_id),
    }


def _base_url() -> str:
    return AUTH_SERVICE_URL.rstrip("/")


def _console_url(path: str) -> str:
    return f"{_base_url()}{path}"


async def _post(client: Any, url: str, body: Mapping[str, Any]) -> Any:
    """POST one signed console call. The signature covers the bytes sent."""
    raw = json.dumps(body, separators=(",", ":")).encode()
    headers = usage_limits.signed_service_headers("POST", urlsplit(url).path, raw)
    headers["Content-Type"] = "application/json"
    return await client.post(url, content=raw, headers=headers)


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "") or ""
    return text.strip()[:300]


def _charged_credits(response: Any, fallback: int) -> int:
    """The console's total when it names one, so the row records what was
    actually debited. A replay reports the original charge, and a retry after
    a price change must not rewrite that number on our side."""
    try:
        body = response.json()
    except Exception:
        return fallback
    value = body.get("charged_credits") if isinstance(body, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return fallback
    return value


async def resolve_org(user_id: str, *, client: Any = None) -> str:
    """The user's Roost organization id.

    The console resolves the Supabase principal through its own membership
    table; a user with no active organization is a 404 and is not something
    this side can invent.
    """
    http = client or await usage_limits.get_http_client()
    try:
        response = await _post(
            http, _console_url(RESOLVE_ORG_PATH), {"user_id": user_id}
        )
    except Exception as e:
        raise BillingError(f"resolve-user unreachable: {type(e).__name__}: {e}") from e
    if response.status_code != 200:
        raise BillingError(
            f"resolve-user HTTP {response.status_code}: {_response_text(response)}",
            status_code=response.status_code,
        )
    try:
        body = response.json()
    except Exception as e:
        raise BillingError(f"resolve-user returned an unreadable body: {e}") from e
    org_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(org_id, str) or not org_id.strip():
        raise BillingError(f"resolve-user returned no org id: {body!r}")
    return org_id.strip()


def _retryable_status(status: int) -> bool:
    return status >= 500 or status in _RETRYABLE_4XX


def _run_seconds(run: Mapping[str, Any]) -> Optional[float]:
    started = run.get("started_at")
    ended = run.get("ended_at")
    if not isinstance(started, datetime) or not isinstance(ended, datetime):
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=UTC)
    return (ended - started).total_seconds()


async def _settle_error(
    run_id: str, message: str, *, credits: Optional[int] = None
) -> None:
    await runs_db.mark_run_billing_error(
        run_id, message[:_ERROR_MAX], final=True, credits=credits
    )


async def _retry_error(run_id: str, message: str) -> None:
    await runs_db.mark_run_billing_error(run_id, message[:_ERROR_MAX], final=False)


async def _org_for_user(
    user_id: str,
    *,
    client: Any,
    org_cache: dict[str, str],
    org_failures: dict[str, BillingError],
) -> str:
    cached = org_cache.get(user_id)
    if cached is not None:
        return cached
    if user_id in org_failures:
        raise org_failures[user_id]
    try:
        org_id = await resolve_org(user_id, client=client)
    except BillingError as e:
        org_failures[user_id] = e
        raise
    org_cache[user_id] = org_id
    return org_id


async def _attempt_run(
    run: Mapping[str, Any],
    *,
    client: Any,
    org_cache: dict[str, str],
    org_failures: dict[str, BillingError],
    prices: SandboxPrices,
    markup_bps: int,
    usd_to_credits: float,
) -> BillingOutcome:
    """Price, resolve and report one run, then record what to do with it next."""
    run_id = str(run["run_id"])
    if run.get("ended_at") is None:
        return BillingOutcome(run_id, "skipped", error="run is still open")
    if run.get("billing_reported_at") is not None:
        return BillingOutcome(run_id, "skipped", error="already reported")
    if not run.get("user_id") or not run.get("provider_sandbox_id"):
        return BillingOutcome(run_id, "skipped", error="no user or provider sandbox id")

    seconds = _run_seconds(run)
    if seconds is None:
        await _settle_error(run_id, "run has no usable start/end timestamps")
        return BillingOutcome(run_id, "failed", error="unusable timestamps")
    if seconds <= 0:
        await _settle_error(
            run_id, f"run has no positive duration ({seconds}s)", credits=0
        )
        return BillingOutcome(run_id, "failed", error="no positive duration")

    cpu = run.get("cpu")
    memory_gb = run.get("memory_gb")
    if cpu is None or memory_gb is None:
        await _settle_error(run_id, "run names no cpu or memory size")
        return BillingOutcome(run_id, "failed", error="missing resources")
    disk_gb = run.get("disk_gb") if run.get("disk_gb") is not None else 0

    try:
        charge = compute_charge(
            cpu,
            memory_gb,
            disk_gb,
            seconds,
            markup_bps,
            usd_to_credits,
            prices=prices,
        )
    except ValueError as e:
        await _settle_error(run_id, f"cannot price run: {e}")
        return BillingOutcome(run_id, "failed", error=str(e))
    if charge.total_credits <= 0:
        await _settle_error(run_id, "run has no billable usage", credits=0)
        return BillingOutcome(run_id, "failed", error="no billable usage")

    try:
        org_id = await _org_for_user(
            str(run["user_id"]),
            client=client,
            org_cache=org_cache,
            org_failures=org_failures,
        )
    except BillingError as e:
        message = f"organization not resolved: {e}"
        await _retry_error(run_id, message)
        return BillingOutcome(
            run_id, "retry", total_credits=charge.total_credits, error=message
        )

    body = build_usage_body(
        run,
        org_id,
        charge,
        prices=prices,
        markup_bps=markup_bps,
        usd_to_credits=usd_to_credits,
    )
    try:
        response = await _post(client, _console_url(REPORT_SANDBOX_PATH), body)
    except Exception as e:
        message = f"usage report unreachable: {type(e).__name__}: {e}"
        await _retry_error(run_id, message)
        return BillingOutcome(
            run_id, "retry", total_credits=charge.total_credits, error=message
        )

    status = int(response.status_code)
    if 200 <= status < 300:
        charged = _charged_credits(response, charge.total_credits)
        await runs_db.mark_run_billed(run_id, charged)
        logger.info(
            "Billed sandbox run %s: %d credits (HTTP %d)",
            run_id,
            charged,
            status,
        )
        return BillingOutcome(
            run_id,
            "reported",
            total_credits=charged,
            http_status=status,
        )

    detail = _response_text(response)
    message = f"usage report HTTP {status}: {detail}"
    if _retryable_status(status):
        await _retry_error(run_id, message)
        logger.warning(
            "Sandbox run %s not billed yet; will retry (HTTP %d): %s",
            run_id,
            status,
            detail,
        )
        return BillingOutcome(
            run_id,
            "retry",
            total_credits=charge.total_credits,
            http_status=status,
            error=message,
        )

    await _settle_error(run_id, message)
    logger.error(
        "Sandbox run %s refused permanently (HTTP %d): %s", run_id, status, detail
    )
    return BillingOutcome(
        run_id,
        "failed",
        total_credits=charge.total_credits,
        http_status=status,
        error=message,
    )


async def report_closed_runs(
    limit: int = 100,
    *,
    client: Any = None,
    prices: Optional[SandboxPrices] = None,
    markup_bps: int = SANDBOX_MARKUP_BPS,
    usd_to_credits: float = USD_TO_CREDITS_RATE,
) -> BillingSweepResult:
    """Report up to ``limit`` closed runs, oldest debt first.

    One organization lookup is shared by the runs of a user in the batch, and
    a failed lookup is remembered so a console outage costs one call per user
    rather than one per run. A failure on one run never stops the rest.
    """
    http = client
    result = BillingSweepResult()
    if not _base_url():
        logger.info("Sandbox billing skipped: AUTH_SERVICE_URL is not configured")
        return result
    if http is None and usage_limits.service_token_missing():
        logger.error(
            "Sandbox billing skipped: INTERNAL_SERVICE_TOKEN is not set, so the "
            "console cannot authenticate this deployment"
        )
        return result
    if http is None:
        http = await usage_limits.get_http_client()
    runs = await runs_db.list_runs_for_billing(limit=limit)
    result.listed = len(runs)
    rates = prices or SandboxPrices()
    org_cache: dict[str, str] = {}
    org_failures: dict[str, BillingError] = {}
    for run in runs:
        try:
            outcome = await _attempt_run(
                run,
                client=http,
                org_cache=org_cache,
                org_failures=org_failures,
                prices=rates,
                markup_bps=markup_bps,
                usd_to_credits=usd_to_credits,
            )
        except Exception as e:
            logger.exception(
                "Sandbox billing failed for run %s: %s", run.get("run_id"), e
            )
            result.failed += 1
            continue
        result.add(outcome)
    if result.reported or result.retried or result.failed:
        logger.info(
            "Sandbox billing: %d reported, %d retrying, %d failed of %d due",
            result.reported,
            result.retried,
            result.failed,
            result.listed,
        )
    return result


async def report_once(
    run_id: str,
    *,
    client: Any = None,
    prices: Optional[SandboxPrices] = None,
    markup_bps: int = SANDBOX_MARKUP_BPS,
    usd_to_credits: float = USD_TO_CREDITS_RATE,
) -> BillingOutcome:
    """Report one named run, for tests and for an operator's retry."""
    run = await runs_db.get_computer_run(run_id)
    if run is None:
        return BillingOutcome(run_id, "skipped", error="run not found")
    http = client or await usage_limits.get_http_client()
    return await _attempt_run(
        run,
        client=http,
        org_cache={},
        org_failures={},
        prices=prices or SandboxPrices(),
        markup_bps=markup_bps,
        usd_to_credits=usd_to_credits,
    )


class SandboxBillingReporter:
    """The per-worker loop that reports billing.

    Every worker may start one; the session lock admits one reporter per cycle
    and the console's idempotency key makes the overlap that remains harmless.
    The loop never raises into startup, and its first pass runs at once so the
    backlog from a deploy is billed without waiting a whole interval.
    """

    _instance: Optional["SandboxBillingReporter"] = None

    def __init__(
        self,
        interval_seconds: Optional[float] = None,
        limit: int = 100,
    ) -> None:
        self.interval_seconds = (
            float(interval_seconds)
            if interval_seconds is not None
            else float(SANDBOX_BILLING_INTERVAL_SECONDS)
        )
        self.limit = limit
        self._task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "SandboxBillingReporter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="sandbox-billing")
        logger.info(
            "Sandbox billing reporter started (interval %ss)", self.interval_seconds
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
                        "Sandbox billing reporter idle: platform gating is inactive"
                    )
                    return
                async with try_own_session_lock(_REPORTER_LOCK) as held:
                    if held:
                        await report_closed_runs(limit=self.limit)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Sandbox billing cycle failed: {type(e).__name__}: {e}")
            await asyncio.sleep(self.interval_seconds)
