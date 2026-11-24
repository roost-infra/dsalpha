"""Fetch Roost Console's billing settings, and keep the process snapshot fresh.

Two figures live on the console and nowhere else: ``fx.usd_to_credits`` (the
USD→credit conversion for dslpha's USD-metered spend) and
``sandbox.markup_bps`` (the sandbox markup). Both are read from the public
price book for fx and from a service-authenticated settings surface for the
markup. Neither is allowed to be a local constant: a local rate is exactly the
drift this migration removes (the old code carried 1000 while the docs said
720).

Failure is not fatal by design. A deployment with no console, or a console
that has never answered, uses the env fallback in
:mod:`src.config.billing_rates`; a console that answered once and then stops
answering keeps the last snapshot, because falling back to the env rate on one
failed GET would silently restate every charge of that window. Startup logs
which case it is in, once.

The fetch is bounded by ``BILLING_RATES_TIMEOUT_SECONDS`` and repeated every
``BILLING_RATES_INTERVAL_SECONDS`` from the refresher started with the server.
Only reads, so every worker may run one.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from src.config import billing_rates as rates_cache
from src.config.billing_rates import BillingRates
from src.config.env import (
    BILLING_RATES_INTERVAL_SECONDS,
    BILLING_RATES_TIMEOUT_SECONDS,
)
from src.config.settings import AUTH_SERVICE_URL
from src.server.dependencies import usage_limits

logger = logging.getLogger(__name__)

# The public book (contract §2.1): fx + model names, no cost columns, no auth.
BOOK_PATH = "/v1/pricing/book"
# The service-authenticated book (contract §2.2) may carry settings alongside
# cost, so it is the first place to look for the markup.
INTERNAL_BOOK_PATH = "/internal/v1/pricing/book"
# Settings surfaces a console may expose for the values that are not part of
# the public book. Tried in order; a 404 simply falls through to the env
# fallback, which is a documented state rather than an error.
SETTINGS_PATHS = ("/internal/v1/settings", "/internal/v1/pricing/settings")

# Log the missing-markup fact once per process. A console that predates the
# settings surface answers every refresh the same way; one warning is the
# signal, a line per cycle is noise.
_markup_fallback_logged = False


def _base_url() -> str:
    return AUTH_SERVICE_URL.rstrip("/")


def _url(path: str) -> str:
    return f"{_base_url()}{path}"


def _number(value: Any) -> Optional[float]:
    """A finite, positive-ish figure from provider-parsed JSON, or None."""
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def fx_from_book(body: Any) -> Optional[float]:
    """``fx.usd_to_credits`` from a pricing-book response.

    The contract puts it at ``fx.usd_to_credits``; a flat
    ``"fx.usd_to_credits"`` key is accepted too, because that is the shape the
    settings table itself uses and the two are easy to confuse at the wire.
    """
    if not isinstance(body, Mapping):
        return None
    fx = body.get("fx")
    if isinstance(fx, Mapping):
        value = _number(fx.get("usd_to_credits"))
        if value is not None and value > 0:
            return value
    return _positive(body.get("fx.usd_to_credits"))


def _positive(value: Any) -> Optional[float]:
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _markup_from_container(container: Any) -> Optional[int]:
    if not isinstance(container, Mapping):
        return None
    for key in ("sandbox.markup_bps", "markup_bps"):
        parsed = _number(container.get(key))
        if parsed is not None and parsed > 0:
            return int(parsed)
    sandbox = container.get("sandbox")
    if isinstance(sandbox, Mapping):
        parsed = _number(sandbox.get("markup_bps"))
        if parsed is not None and parsed > 0:
            return int(parsed)
    return None


def markup_bps_from_body(body: Any) -> Optional[int]:
    """``sandbox.markup_bps`` from a settings or book response.

    Accepted shapes: flat ``"sandbox.markup_bps"`` (the settings key verbatim),
    nested ``{"sandbox": {"markup_bps": …}}``, or either of those under
    ``settings`` / ``values`` / ``data``. A response whose shape this side has
    not learned yields None, and the caller falls back rather than guesses.
    """
    if not isinstance(body, Mapping):
        return None
    for candidate in (
        body,
        body.get("settings"),
        body.get("values"),
        body.get("data"),
    ):
        found = _markup_from_container(candidate)
        if found is not None:
            return found
    return None


def model_names_from_book(body: Any) -> tuple[str, ...]:
    """The model spellings the public book currently prices."""
    if not isinstance(body, Mapping):
        return ()
    models = body.get("models")
    if not isinstance(models, list):
        return ()
    names = []
    for entry in models:
        name = entry.get("model") if isinstance(entry, Mapping) else None
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return tuple(dict.fromkeys(names))


def settings_version_from_book(body: Any) -> Optional[str]:
    if not isinstance(body, Mapping):
        return None
    version = body.get("version") or body.get("settings_version")
    return version if isinstance(version, str) and version.strip() else None


async def _get_json(client: Any, path: str, *, client_signed: bool) -> Any:
    """One bounded GET. None on any failure — callers own the fallback."""
    url = _url(path)
    headers = {}
    if client_signed:
        headers = usage_limits.signed_service_headers(
            "GET", urlsplit(url).path, b""
        )
    try:
        response = await asyncio.wait_for(
            client.get(url, headers=headers, timeout=BILLING_RATES_TIMEOUT_SECONDS),
            timeout=BILLING_RATES_TIMEOUT_SECONDS + 1.0,
        )
    except Exception as e:
        logger.warning("[Billing] GET %s failed: %s", path, e)
        return None
    if int(getattr(response, "status_code", 0)) != 200:
        logger.debug(
            "[Billing] GET %s returned %s", path, getattr(response, "status_code", "?")
        )
        return None
    try:
        return response.json()
    except Exception:
        return None


def _book_query() -> str:
    """The public book's query string.

    ``currency=CREDIT`` is the contract's requested unit; ``at`` is optional on
    the console but always valid, so sending it keeps this working against a
    deployment that requires one.
    """
    from urllib.parse import urlencode

    return "?" + urlencode(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "currency": "CREDIT",
        }
    )


async def fetch_billing_rates(*, client: Any = None) -> BillingRates:
    """Read the console's live billing settings, falling back where silent.

    The public book supplies fx and the model spellings. The markup comes from
    the first service-authenticated surface that names it; if none does, the
    env fallback is used and the fact is logged once, because that is a
    deployment state an operator has to know about (the previous code silently
    used a hard-coded markup that disagreed with the console's).
    """
    http = client
    if http is None:
        http = await usage_limits.get_http_client()

    public_book = await _get_json(
        http, BOOK_PATH + _book_query(), client_signed=False
    )
    fx = fx_from_book(public_book)
    book_models = model_names_from_book(public_book)
    version = settings_version_from_book(public_book)

    markup: Optional[int] = markup_bps_from_body(public_book)
    markup_source = rates_cache.SOURCE_CONSOLE if markup is not None else None
    if markup is None:
        internal_book = await _get_json(
            http, INTERNAL_BOOK_PATH + _book_query(), client_signed=True
        )
        markup = markup_bps_from_body(internal_book)
        if markup is not None:
            markup_source = rates_cache.SOURCE_CONSOLE
            fx = fx or fx_from_book(internal_book)
            book_models = book_models or model_names_from_book(internal_book)
            version = version or settings_version_from_book(internal_book)
    if markup is None:
        for path in SETTINGS_PATHS:
            settings = await _get_json(http, path, client_signed=True)
            markup = markup_bps_from_body(settings)
            if markup is not None:
                markup_source = rates_cache.SOURCE_CONSOLE
                break
    if markup is None:
        global _markup_fallback_logged
        markup = rates_cache.ENV_SANDBOX_MARKUP_BPS
        markup_source = rates_cache.SOURCE_ENV
        if not _markup_fallback_logged:
            _markup_fallback_logged = True
            logger.warning(
                "[Billing] the console names no sandbox.markup_bps; using the "
                "env fallback %s bps. The console setting is authoritative once "
                "it is exposed.",
                markup,
            )

    return BillingRates(
        usd_to_credits=fx if fx is not None else rates_cache.ENV_USD_TO_CREDITS,
        markup_bps=int(markup),
        source=rates_cache.SOURCE_CONSOLE if fx is not None else rates_cache.SOURCE_ENV,
        markup_source=markup_source or rates_cache.SOURCE_ENV,
        console_fx=fx,
        book_models=book_models,
        settings_version=version,
    )


async def refresh_billing_rates(*, client: Any = None) -> BillingRates:
    """One refresh cycle, installed into the process snapshot.

    Never raises: startup and the periodic loop both call it, and neither may
    be taken down by a console outage. A failed fetch leaves the previous
    snapshot in place; only a process that has never fetched falls back to env.
    """
    if not _base_url():
        previous = rates_cache.snapshot()
        return previous or rates_cache.apply(rates_cache.env_fallback())
    if usage_limits.service_token_missing():
        logger.error(
            "[Billing] INTERNAL_SERVICE_TOKEN is not set; the console cannot "
            "authenticate the settings fetch, so the env fallback stays in use"
        )
        previous = rates_cache.snapshot()
        return previous or rates_cache.apply(rates_cache.env_fallback())
    try:
        fetched = await fetch_billing_rates(client=client)
    except Exception as e:
        logger.warning(
            "[Billing] billing settings fetch failed (%s: %s); keeping the %s snapshot",
            type(e).__name__,
            e,
            "current" if rates_cache.snapshot() else "env",
        )
        return rates_cache.current()
    previous = rates_cache.snapshot()
    if (
        not fetched.from_console
        and fetched.markup_source != rates_cache.SOURCE_CONSOLE
    ):
        # Nothing at all came back (each GET failed or answered without a
        # figure). Keep whatever was published before: one failed refresh must
        # not move every charge of the window onto the env fallback.
        if previous is not None:
            logger.warning(
                "[Billing] the console answered with no billing settings; "
                "keeping the last published snapshot (fx %.1f, markup %s bps)",
                previous.usd_to_credits,
                previous.markup_bps,
            )
            return previous
    elif (
        previous is not None
        and previous.markup_source == rates_cache.SOURCE_CONSOLE
        and fetched.markup_source != rates_cache.SOURCE_CONSOLE
    ):
        # One half of the settings surface went missing while the other
        # answered. Keep the last published markup instead of silently moving
        # every sandbox charge onto the env fallback.
        fetched = replace(
            fetched,
            markup_bps=previous.markup_bps,
            markup_source=previous.markup_source,
        )
    installed = rates_cache.apply(
        fetched, ttl_seconds=float(BILLING_RATES_INTERVAL_SECONDS)
    )
    if installed.from_console:
        logger.info(
            "[Billing] console settings %.1f usd→credits, markup %s bps%s",
            installed.usd_to_credits,
            installed.markup_bps,
            f" (book {installed.settings_version})" if installed.settings_version else "",
        )
    else:
        logger.warning(
            "[Billing] the console published no usable fx.usd_to_credits; "
            "using the env fallback %.1f usd→credits",
            installed.usd_to_credits,
        )
    return installed


async def ensure_console_rates(
    *, max_age_seconds: Optional[float] = None, client: Any = None
) -> BillingRates:
    """Snapshot if fresh enough, refresh otherwise. Used at startup."""
    snapshot = rates_cache.snapshot()
    if snapshot is not None and snapshot.is_fresh():
        return snapshot
    if not usage_limits.platform_gating_active():
        return rates_cache.current()
    return await refresh_billing_rates(client=client)


class BillingRatesRefresher:
    """Per-worker loop that keeps fx/markup within one interval of the console.

    Every worker may run one; the fetch is two reads and the snapshot is
    per-process, so no lock is needed. The loop never raises into startup, and
    its first sleep happens before the first refresh because startup already
    awaited one.
    """

    _instance: Optional["BillingRatesRefresher"] = None

    def __init__(self, interval_seconds: Optional[float] = None) -> None:
        self.interval_seconds = (
            float(interval_seconds)
            if interval_seconds is not None
            else float(BILLING_RATES_INTERVAL_SECONDS)
        )
        self._task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "BillingRatesRefresher":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="billing-rates")
        logger.info(
            "[Billing] settings refresher started (interval %ss)", self.interval_seconds
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.interval_seconds)
                if not usage_limits.platform_gating_active():
                    continue
                await refresh_billing_rates()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "[Billing] settings refresh cycle failed: %s: %s",
                    type(e).__name__,
                    e,
                )


__all__ = [
    "BillingRatesRefresher",
    "BOOK_PATH",
    "INTERNAL_BOOK_PATH",
    "SETTINGS_PATHS",
    "ensure_console_rates",
    "fetch_billing_rates",
    "fx_from_book",
    "markup_bps_from_body",
    "model_names_from_book",
    "refresh_billing_rates",
]
