"""Server wiring for the runtime credit gate.

The gate middleware (``ptc_agent.agent.middleware.credit_gate``) is
deployment-agnostic: it talks to a duck-typed port. This module is the
platform-mode implementation — leases against the quota service's
``/api/auth/billing/leases`` endpoints, heartbeats into this service's own
run ledgers — and the factory that decides whether a run gets a gate at
all. With platform gating inactive (OSS mode or no ``AUTH_SERVICE_URL``)
the factory returns None and the gate never engages.
"""

import asyncio
import json
import logging
import math
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone
from typing import Any, Optional

from ptc_agent.agent.middleware.credit_gate import (
    LEASE_RENEW_MARGIN_SECONDS,
    CreditGateState,
    CreditLease,
    LeaseVerdict,
)

from src.config import billing_rates
from src.config.settings import AUTH_SERVICE_URL
from src.llms.pricing_utils import chunk_multiplier
from src.server.database.runs import billing_settlement as settlement_db
from src.server.database.runs import credit_ledger
from src.server.dependencies import usage_limits
from src.server.services import billing_rates as console_rates
from src.utils.tracking.model_usage import (
    ReleaseSettlement,
    credits_to_minor,
    price_difference_ratio,
)

logger = logging.getLogger(__name__)

# Stand-in when the service does not say when the lease expires. Comfortably
# above the gate's renew margin on purpose: the renewal cadence degrades to a
# slow poll rather than a hot one, and the gate keeps enforcing the ceiling it
# was granted in the meantime.
_UNKNOWN_TTL_SECONDS = 300.0

# A figure this large is a metering bug on our side, not a spend. Declining to
# send it fails open for one tick, which the next heartbeat corrects — cheaper
# than asking for a ceiling sized off a number we do not believe.
_MAX_REPORTABLE_SPEND = 1_000_000.0

# Bounds on the multiplier we are willing to send. The floor keeps a bad rate
# from asking for a reservation too small to cover a single call; the ceiling
# keeps one from reserving a user's whole balance against one turn. A figure
# outside them is a manifest or arithmetic fault, not a price.
_MIN_RATE_MULTIPLIER = 0.1
_MAX_RATE_MULTIPLIER = 100.0


def _reportable_multiplier(value: Any) -> float:
    """Clamp to something a reservation can be sized from. Never raises: this
    sits on the acquire path, where a bad number must cost precision rather
    than the verdict itself."""
    try:
        m = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(m):
        return 1.0
    return min(max(m, _MIN_RATE_MULTIPLIER), _MAX_RATE_MULTIPLIER)


# A lost release is not free: the reservation holds the entire ceiling it was
# granted until the TTL expires, and that is exactly the window a user who has
# just topped up spends trying to resume. Worth a couple of seconds of teardown
# to avoid, and no more — the TTL is the backstop either way. One waits between
# attempts, so the attempt count is this plus the first try.
_RELEASE_BACKOFF_SECONDS = (0.5, 1.5)
_RELEASE_ATTEMPTS = len(_RELEASE_BACKOFF_SECONDS) + 1

# 4xx answers a later attempt (or a top-up) can change. 404/409 are handled
# before this set is consulted: both mean the lease is already retired.
_RETRYABLE_RELEASE_4XX = frozenset({401, 402, 403, 408, 425, 429})

# The ceiling that makes "and no more" true. Retries and backoffs bound the
# attempts but not the wait: a service that accepts connections and then does
# not answer gives every attempt the shared client's full timeout, and the
# teardown this sits in is what ends the user's stream. Sized so a service that
# is merely failing still gets all three attempts, while one that is hanging
# costs a single client timeout instead of three plus the backoffs.
_RELEASE_BUDGET_SECONDS = 5.0

# Bounded separately from the shared client's default: this one runs inside
# startup, where a slow answer delays every worker's boot.
_CAPABILITY_TIMEOUT_SECONDS = 5.0


def _reportable_spend(value: Any, run_ref: str) -> Optional[float]:
    """The figure, or None when it is a metering fault rather than a spend.

    The lease and the ledger refuse the same values, and the ledger is the
    reason they must: its write is monotone and Postgres ranks NaN above every
    real numeric, so an unusable figure that lands once can never be lowered by
    a later correct one, and it carries through the per-user SUM to every other
    run that user has open.
    """
    try:
        spent = float(value)
    except (TypeError, ValueError):
        spent = float("nan")
    if not math.isfinite(spent) or spent > _MAX_REPORTABLE_SPEND:
        logger.error(
            "[CreditGate] not reporting spend %r for run %s — outside the "
            "range this deployment will record",
            value,
            run_ref,
        )
        return None
    return spent


def _token_hint() -> str:
    """Names the one acquire failure that no amount of retrying resolves."""
    return (
        "; INTERNAL_SERVICE_TOKEN is not set"
        if usage_limits.service_token_missing()
        else ""
    )


def _log_acquire_failure(status_code: int, run_ref: str, text: str) -> None:
    """Fail open either way, but say which failure it was."""
    if status_code in (401, 403):
        # This deployment cannot ask at all, so the gate is off for every run
        # on it and stays off until someone notices.
        logger.error(
            "[CreditGate] lease acquire rejected with %d — the runtime credit "
            "gate is inactive for every run on this deployment%s",
            status_code,
            _token_hint(),
        )
    elif status_code == 404:
        # Ambiguous on its own: an unknown principal and a route this build is
        # looking for in the wrong place answer the same way. The startup
        # capability check is what separates them.
        logger.error(
            "[CreditGate] lease acquire returned 404 for run %s — an unknown "
            "user, or the lease route is elsewhere in this deployment. Neither "
            "resolves by asking again.",
            run_ref,
        )
    else:
        logger.warning(
            "[CreditGate] lease acquire returned %d: %s", status_code, text[:200]
        )


def _ttl_seconds(body: dict) -> float:
    """Seconds until the grant lapses.

    ``expires_in_seconds`` wins over differencing ``expires_at``: the service
    differences it against its own clock, so the answer carries none of the skew
    between the two hosts. Subtracting an absolute stamp from a local ``now()``
    does, and skew big enough to eat the renew margin parks every lease inside
    its renew window for the whole turn.

    Falls back to a stand-in rather than to zero: an unreadable expiry read as
    "expires now" has exactly that effect.
    """
    remaining = body.get("expires_in_seconds")
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        return max(float(remaining), 0.0)
    expires_at = body.get("expires_at")
    if not expires_at:
        return _UNKNOWN_TTL_SECONDS
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        return max((expiry - datetime.now(timezone.utc)).total_seconds(), 0.0)
    except Exception:
        # Naive timestamps land here: they parse, then the subtraction raises
        # because the other side is aware.
        logger.warning(
            "[CreditGate] lease expires_at unreadable (%r); assuming a %.0fs TTL",
            expires_at,
            _UNKNOWN_TTL_SECONDS,
        )
        return _UNKNOWN_TTL_SECONDS


def _normalize_verdict(body: Any) -> Optional[LeaseVerdict]:
    """The service's answer as the gate's own type, or None when it is not one.

    An unreadable answer is not an answer: collapsing it into ``granted=False``
    records a denial with no ceiling, which stops the turn at its first model
    boundary.
    """
    if not isinstance(body, dict) or "granted" not in body:
        logger.warning("[CreditGate] lease acquire body unusable: %.200s", body)
        return None
    # Strictly the boolean the contract declares. bool() would read the string
    # "false", or any non-empty string, as a grant.
    granted = body.get("granted")
    if not isinstance(granted, bool):
        logger.warning(
            "[CreditGate] lease acquire 'granted' not a boolean: %r", granted
        )
        return None
    ceiling = 0.0
    if granted:
        # A grant whose ceiling will not read as a number is not usable as one.
        try:
            ceiling = float(body.get("ceiling_credits") or 0.0)
        except (TypeError, ValueError):
            logger.warning(
                "[CreditGate] lease acquire ceiling unusable: %r",
                body.get("ceiling_credits"),
            )
            return None
    # Anything but a plain integer leaves that release unfenced, which is the
    # shape before the service offered a fence, not a failure. ``bool`` is an
    # ``int`` in Python and is not one of these.
    generation = body.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int):
        generation = None
    quota = body.get("quota")
    return LeaseVerdict(
        granted=granted,
        ceiling_credits=ceiling,
        ttl_seconds=_ttl_seconds(body),
        generation=generation,
        quota=quota if isinstance(quota, dict) else None,
    )


class PlatformCreditGatePort:
    """Lease + heartbeat operations for one deployment. Stateless."""

    def _url(self, path: str) -> str:
        return f"{AUTH_SERVICE_URL.rstrip('/')}/api/auth/billing/leases/{path}"

    async def acquire(
        self,
        user_id: str,
        run_ref: str,
        spent_credits: float,
        rate_multiplier: float = 1.0,
        byok: bool = False,
    ) -> Optional[LeaseVerdict]:
        """One lease acquire/extend attempt. None = no verdict (fail open):
        transport failure, any non-200, an unreadable body. A 200 is the
        service's answer — grant or denial — normalized for the gate.

        ``rate_multiplier`` is how much one model boundary on this turn costs
        against the baseline the service sizes reservations in. Advisory: the
        service decides what to do with it, and a build that sends nothing gets
        whatever default it already applied.

        ``byok`` travels for the same reason admission sends it, and on the same
        terms: the service cannot reproduce its own admission verdict without
        knowing whether the turn runs on a key the user pays for. Sent only when
        true, so the payload is unchanged for the platform-funded case.
        """
        spent = _reportable_spend(spent_credits, run_ref)
        if spent is None:
            # No verdict rather than a rejected request: the gate keeps
            # enforcing the ceiling it already holds, and nothing unusable
            # reaches the reservation.
            return None
        client = await usage_limits.get_http_client()
        body: dict[str, Any] = {
            "user_id": user_id,
            "run_ref": run_ref,
            "spent_credits": max(spent, 0.0),
            "rate_multiplier": _reportable_multiplier(rate_multiplier),
        }
        if byok:
            body["byok"] = True
        raw_body = json.dumps(body, separators=(",", ":")).encode()
        acquire_url = self._url("acquire")
        try:
            resp = await client.post(
                acquire_url,
                json=body,
                headers=usage_limits.signed_service_headers("POST", urlsplit(acquire_url).path, raw_body),
            )
        except Exception as e:
            logger.warning("[CreditGate] lease service unreachable: %s", e)
            return None
        if resp.status_code != 200:
            _log_acquire_failure(resp.status_code, run_ref, resp.text)
            return None
        try:
            body = resp.json()
        except Exception:
            return None
        return _normalize_verdict(body)

    async def release(
        self,
        user_id: str,
        run_ref: str,
        generation: Optional[int] = None,
        settlement: Optional[ReleaseSettlement] = None,
    ) -> None:
        """Retire the run's reservation and settle what it spent.

        ``generation`` fences it against a lane that rejoined and re-acquired
        while this teardown was in flight: the release names the grant it is
        retiring, so it cannot retire one this teardown never held. Omitted,
        the release is unconditional and that race is live.

        ``settlement`` is what the turn's own tracker saw: per-model token
        usage plus the platform USD figure, which is the contract's
        authoritative release input. It is what makes the console price the
        turn from the shared book instead of from a scalar. When it is absent,
        or carries no model calls, the ledger's heartbeated ``in_flight``
        figure is the fallback — and if *that* cannot be read, the lease is
        deliberately left standing and the run is marked ``settle_pending``:
        releasing with no figure at all retires the whole reserved ceiling and
        gives the turn away. The settlement worker reads the run's usage row
        (finalize commits it after this runs) and settles then.

        Retried only for the failures a second attempt can fix. A 4xx is an
        answer — including the 404 that means there was nothing to release,
        which is the idempotent case, not an error.

        Bounded by a whole-teardown deadline rather than per attempt, because
        it is the total that the caller waits out: this runs from the lane's
        ``aclose``, so until it returns the turn's stream has stopped producing
        but has not ended.
        """
        client = await usage_limits.get_http_client()
        payload: dict[str, Any] = {"user_id": user_id, "run_ref": run_ref}
        if generation is not None:
            payload["generation"] = generation

        model_usage = [
            {**entry, "model": billing_rates.console_model_name(entry["model"])}
            for entry in (settlement.model_usage if settlement else ())
        ]
        spent_usd = settlement.spent_usd if settlement else None
        infra_credits = settlement.infra_credits if settlement else None
        has_model_usage = bool(model_usage)
        has_settlement = has_model_usage or spent_usd is not None

        # Best-effort even when a settlement was passed: the legacy
        # ``spent_credits`` field is what an old quota service settles from,
        # and it also carries infrastructure credits the model payload does
        # not (the contract's release body has no tool charges).
        in_flight: Optional[float] = None
        in_flight_error: Optional[str] = None
        try:
            in_flight = await credit_ledger.in_flight_credits(run_ref)
        except Exception as e:
            in_flight_error = f"{type(e).__name__}: {e}"
            logger.warning(
                "[CreditGate] could not read settle spend for %s", run_ref,
                exc_info=True,
            )

        if settlement is not None and settlement.byok:
            payload["byok"] = True
        # Non-token platform spend (tools and other metered infrastructure) is
        # its own field: Console prices the token side from model_usage, so a
        # token-shaped scalar holding both would either be ignored (the legacy
        # field) or double-charge the tokens. Sent whenever it is known, even
        # on the in-flight fallback path, so infrastructure is never lost.
        surcharge_minor = (
            credits_to_minor(infra_credits) if infra_credits is not None else None
        )
        if surcharge_minor is not None and surcharge_minor > 0:
            payload["surcharge_minor"] = surcharge_minor

        if has_settlement:
            if has_model_usage:
                payload["model_usage"] = model_usage
            if spent_usd is not None:
                payload["spent_usd"] = round(float(spent_usd), 10)
            if in_flight is not None and in_flight > 0:
                # Full legacy figure (tokens + infrastructure) for the old
                # quota service. Console ignores it once model_usage /
                # spent_usd carry the token side and surcharge_minor the rest.
                payload["spent_credits"] = in_flight
            elif spent_usd is not None:
                # Rebuild the same full figure when the heartbeat is
                # unreadable, so the legacy path is not silently short by the
                # infrastructure part.
                payload["spent_credits"] = round(
                    float(spent_usd) * billing_rates.usd_to_credits_rate()
                    + float(infra_credits or 0.0),
                    6,
                )
        elif in_flight is None:
            await self._leave_pending(
                run_ref,
                "in_flight_credits unreadable"
                + (f": {in_flight_error}" if in_flight_error else ""),
            )
            return
        elif in_flight > 0:
            payload["spent_credits"] = in_flight

        outcome = await self._post_release(client, run_ref, payload)
        if outcome == "sent":
            return
        if outcome.startswith("refused:"):
            # A refusal another attempt cannot change. Leave the queue with the
            # reason recorded rather than retrying it forever; the log is the
            # operator's signal.
            try:
                await settlement_db.mark_settled(
                    run_ref, detail=f"release {outcome}"
                )
            except Exception:
                logger.error(
                    "[CreditGate] run %s was refused (%s) and could not be "
                    "recorded",
                    run_ref,
                    outcome,
                    exc_info=True,
                )
            return
        # Every attempt failed on a retryable answer. The lease will expire
        # un-billed, which is the leak this queue exists to close.
        await self._leave_pending(run_ref, f"release failed ({outcome})")

    async def _leave_pending(self, run_ref: str, reason: str) -> None:
        """Queue the run for settlement by the worker, and say so.

        Called only on the path that does not release. If even the marker
        cannot be written the run is un-settled and the log is the only
        evidence; that is a database outage, not a billing decision.
        """
        try:
            queued = await settlement_db.mark_settle_pending(run_ref, reason)
        except Exception:
            logger.error(
                "[CreditGate] run %s has no settle figure and could not be "
                "queued for settlement (%s); its spend is unrecorded",
                run_ref,
                reason,
                exc_info=True,
            )
            return
        if queued:
            logger.warning(
                "[CreditGate] run %s left unreleased for settlement: %s",
                run_ref,
                reason,
            )
        else:
            logger.warning(
                "[CreditGate] run %s could not be settled (%s) and its ledger "
                "row was already settled",
                run_ref,
                reason,
            )

    async def _post_release(
        self, client: Any, run_ref: str, payload: dict[str, Any]
    ) -> str:
        """Post the release with bounded retries.

        Answers split three ways: settled (2xx, or 404/409 — nothing left to
        retire, or already retired), a permanent refusal (another attempt
        cannot change a 400/422), and everything else (a 4xx that a top-up or a
        fixed secret resolves, plus 5xx/network). A permanent refusal returns
        ``"refused: HTTP n"`` so the caller can stamp the run with its reason
        and leave the queue; the rest returns a failure description and queues
        the run for the settlement worker.
        """
        detail = "no attempt made"
        deadline = time.monotonic() + _RELEASE_BUDGET_SECONDS
        model_usage_sent = "model_usage" in payload
        spent_usd = payload.get("spent_usd")
        # The priced comparison must include the non-token surcharge, or an
        # infra-bearing turn always reads as a disagreement.
        extra_credits = float(payload.get("surcharge_minor") or 0) / 1000.0
        for attempt in range(_RELEASE_ATTEMPTS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                detail = f"{detail}; teardown budget spent"
                break
            raw_payload = json.dumps(payload, separators=(",", ":")).encode()
            release_url = self._url("release")
            try:
                resp = await client.post(
                    release_url,
                    json=payload,
                    headers=usage_limits.signed_service_headers("POST", urlsplit(release_url).path, raw_payload),
                    timeout=remaining,
                )
            except Exception as e:
                detail = str(e)
            else:
                status = int(resp.status_code)
                if 200 <= status < 300 or status in (404, 409):
                    await self._record_release(
                        run_ref,
                        resp,
                        spent_usd,
                        model_usage_sent,
                        extra_credits,
                    )
                    return "sent"
                if status < 500 and status not in _RETRYABLE_RELEASE_4XX:
                    detail = f"HTTP {status}"
                    logger.error(
                        "[CreditGate] lease release of run %s refused permanently "
                        "(HTTP %d): %.200s",
                        run_ref,
                        status,
                        getattr(resp, "text", "") or "",
                    )
                    return f"refused: {detail}"
                detail = f"HTTP {status}"
            if attempt < len(_RELEASE_BACKOFF_SECONDS):
                backoff = min(
                    _RELEASE_BACKOFF_SECONDS[attempt],
                    max(0.0, deadline - time.monotonic()),
                )
                await asyncio.sleep(backoff)
        logger.warning(
            "[CreditGate] lease release failed for run %s after %d attempts "
            "(%s); its reservation stands until the lease expires",
            run_ref,
            _RELEASE_ATTEMPTS,
            detail,
        )
        return detail

    async def _record_release(
        self,
        run_ref: str,
        response: Any,
        spent_usd: Any,
        model_usage_sent: bool,
        extra_credits: Any = None,
    ) -> None:
        """Record what the console answered, and report a pricing disagreement.

        The run is stamped settled with the console's ``charged_credits`` so
        the local record matches the ledger. The comparison against
        ``spent_usd × fx`` is the migration's day report: it is expected to
        disagree once the book prices a turn, and a model over 5% moves the
        fallback out of service deliberately.
        """
        try:
            body = response.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            body = {}
        charged = body.get("charged_credits")
        if isinstance(charged, bool) or not isinstance(charged, int):
            charged = None
        if body.get("fallback") is True:
            logger.warning(
                "[CreditGate] release of run %s fell back to the scalar "
                "spent_usd price (a model was not in the price book)",
                run_ref,
            )
        ratio = price_difference_ratio(
            charged,
            spent_usd,
            billing_rates.usd_to_credits_rate(),
            extra_credits=extra_credits,
        )
        if ratio is not None and ratio > 0.05:
            logger.warning(
                "[CreditGate] release of run %s charged %d credits, %.1f%% off "
                "the spent_usd estimate%s",
                run_ref,
                charged,
                ratio * 100.0,
                "" if model_usage_sent else " (no model_usage was sent)",
            )
        try:
            queued = await settlement_db.mark_settled(
                run_ref, charged_credits=charged, detail="released"
            )
        except Exception:
            queued = False
        if not queued:
            logger.debug(
                "[CreditGate] release of run %s settled outside the local "
                "pending queue",
                run_ref,
            )

    async def capability(self) -> Optional[dict]:
        """What the lease service reports about itself, or None if it did not
        answer. Read-only on both sides, so every worker asking at boot costs
        nothing."""
        client = await usage_limits.get_http_client()
        try:
            capability_url = self._url("capability")
            resp = await client.get(
                capability_url,
                headers=usage_limits.signed_service_headers("GET", urlsplit(capability_url).path, b""),
                timeout=_CAPABILITY_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.warning("[CreditGate] capability check unreachable: %s", e)
            return None
        if resp.status_code != 200:
            logger.error(
                "[CreditGate] capability check returned %d — the runtime "
                "credit gate cannot reach its lease service at %s, so every "
                "long-running turn on this deployment goes ungated%s",
                resp.status_code,
                self._url("capability"),
                _token_hint(),
            )
            return None
        try:
            body = resp.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            logger.error("[CreditGate] capability body unusable: %s", resp.text[:200])
            return None
        return body

    async def heartbeat(
        self, kind: credit_ledger.RunKind, run_ref: str, credits: float
    ) -> Optional[bool]:
        """True when the row took the value, False when it is no longer open,
        None when there was nothing worth writing.

        Validated on the same terms as ``acquire``: a beat is the write that
        actually has to hold the line, since the ledger keeps whatever lands
        on it.
        """
        spent = _reportable_spend(credits, run_ref)
        if spent is None:
            return None
        return await credit_ledger.heartbeat(kind, run_ref, spent)


_port = PlatformCreditGatePort()


def build_run_credit_gate(
    user_id: str,
    run_id: str,
    token_callback: Any,
    tool_tracker: Any,
    model_name: Optional[str] = None,
    is_byok: bool = False,
) -> Optional[CreditGateState]:
    """The main lane's gate state, or None when platform gating is inactive.

    Also mints the turn's lease, which this lane and every subagent it
    spawns share. Admission (``enforce_credit_limit``) has already allowed
    this run by the time this is called, which is the gate's seed verdict —
    the first model boundary proceeds on it while the lease's first acquire
    is in flight.

    No gate without a principal: a heartbeat onto a ``user_id IS NULL`` row
    would spend against an aggregate that can never see it.
    """
    if not user_id or not usage_limits.platform_gating_active():
        return None
    return CreditGateState(
        run_ref=run_id,
        kind="run",
        port=_port,
        lease=CreditLease(
            user_id=user_id, run_ref=run_id, port=_port, is_byok=is_byok
        ),
        tracker=token_callback,
        tool_tracker=tool_tracker,
        rate_multiplier=_model_rate_multiplier(model_name, is_byok),
    )


def _model_rate_multiplier(model_name: Optional[str], is_byok: bool = False) -> float:
    """What one boundary on this model costs against the baseline, or 1.0.

    A BYOK turn pays its tokens to the user's own vendor account, so the only
    thing left to meter is infrastructure, and an infrastructure credit is
    computed from tool-use counts alone -- there is no model term anywhere in
    ``calculate_infrastructure_credits``. So the rate is not a large estimate
    of that spend, it is an unrelated one, and scaling the reservation by it
    sizes the ask on a quantity the spend cannot vary with.

    Resolved per turn rather than cached: the answer moves with the manifest,
    and for a model on hourly pricing it moves with the clock. Never raises —
    an unreadable rate costs the reservation its sizing, not the turn.
    """
    if is_byok or not model_name:
        return 1.0
    try:
        return chunk_multiplier(model_name) or 1.0
    except Exception:
        logger.warning(
            "[CreditGate] could not size a rate for %r; reserving at baseline",
            model_name,
            exc_info=True,
        )
        return 1.0


async def verify_credit_gate_wiring() -> None:
    """Startup assertion for the runtime credit gate. Never raises.

    The gate has two ways to die without producing a single error at request
    time. A lease route that is not where this build looks leaves every
    long-running turn ungated, and a granted TTL at or below the renew margin
    puts each lease inside the renew window the moment it is issued, so the
    refresher re-acquires for the whole turn — load with nothing to show for
    it. One GET answers both at boot instead of in a bill.

    Silent when gating is inactive: OSS builds have no service to ask.
    """
    if not usage_limits.platform_gating_active():
        return
    # Before the capability check, and on every platform deployment rather than
    # only a healthy one: fx/markup are also what the sandbox reporter prices
    # with, and that loop runs whether or not lease reservations are on.
    await _verify_billing_rates()
    body = await _port.capability()
    if body is None:
        return  # the check logged what it found
    if not body.get("enabled"):
        logger.info(
            "[CreditGate] lease reservations are switched off on the quota "
            "service; turns run without a runtime credit gate"
        )
        return
    ttl = body.get("lease_ttl_seconds")
    if not isinstance(ttl, (int, float)) or isinstance(ttl, bool):
        logger.error("[CreditGate] capability reported no usable TTL: %r", ttl)
        return
    if ttl <= LEASE_RENEW_MARGIN_SECONDS:
        logger.error(
            "[CreditGate] lease TTL is %ss against a %ss renew margin — every "
            "lease arrives already due for renewal, so runs will re-acquire "
            "continuously instead of gating",
            ttl,
            LEASE_RENEW_MARGIN_SECONDS,
        )
        return
    lo = body.get("rate_multiplier_min")
    hi = body.get("rate_multiplier_max")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        if float(lo) != _MIN_RATE_MULTIPLIER or float(hi) != _MAX_RATE_MULTIPLIER:
            logger.error(
                "[CreditGate] multiplier bounds disagree: the service accepts "
                "[%s, %s], this build clamps to [%s, %s]. A multiplier outside "
                "the service's range is rejected, and a rejected acquire is no "
                "verdict, which leaves the turn ungated.",
                lo,
                hi,
                _MIN_RATE_MULTIPLIER,
                _MAX_RATE_MULTIPLIER,
            )
    logger.info("[CreditGate] lease service ready (TTL %ss)", ttl)


async def _verify_billing_rates() -> None:
    """Refresh the console's fx/markup and report where they came from.

    The old check compared a local env rate with a hard-coded canonical unit
    and therefore fired on every correctly configured deployment (720 vs
    1000). The rate now has one source — the console's ``settings`` — and the
    only local failure left is "the console never answered", which startup is
    the first place able to see. A stale but previously fetched snapshot is
    not an error; the refresher will heal it.
    """
    try:
        rates = await console_rates.ensure_console_rates()
    except Exception:
        logger.warning("[CreditGate] billing settings refresh failed", exc_info=True)
        return
    if not rates.from_console:
        logger.error(
            "[CreditGate] fx.usd_to_credits was not read from the console; "
            "using the env fallback %.1f. A platform deployment whose rate is "
            "not console-published cannot be reconciled against its ledger.",
            rates.usd_to_credits,
        )
        return
    if (
        rates.console_fx is not None
        and abs(float(rates.console_fx) - billing_rates.ENV_USD_TO_CREDITS) > 0.5
    ):
        logger.warning(
            "[CreditGate] the console publishes fx=%s, but this deployment's "
            "USD_TO_CREDITS_RATE is %s. The console value is used; the env "
            "value only applies when the console is unreachable.",
            rates.console_fx,
            billing_rates.ENV_USD_TO_CREDITS,
        )
    if rates.markup_source != billing_rates.SOURCE_CONSOLE:
        logger.warning(
            "[CreditGate] the console publishes no sandbox.markup_bps; the "
            "sandbox price uses the env fallback %s bps",
            rates.markup_bps,
        )
