"""The deployment's billing rates, as Roost Console publishes them.

Roost Console owns the only price fact source: ``settings`` carries
``fx.usd_to_credits`` (the USD→credit conversion dsalpha needs, since its own
metering is USD) and ``sandbox.markup_bps`` (the sandbox markup). This module
is the process-wide snapshot of those two figures plus the model names the
public price book currently lists, so the release path can name a model the
way Console spells it (``claude-sonnet-5.5``) while the manifest keys it by
hyphen (``claude-sonnet-5-5``).

It holds no I/O of its own: the fetch lives in
``src.server.services.billing_rates`` because signing a service call and
opening an HTTP client are server-tier concerns, while the agent middleware
needs the same numbers without importing the server. The environment values
in :mod:`src.config.env` are the fallback for an OSS build, a deployment with
no Console, or a Console that has never answered — never the source of truth
in a platform deployment.

The snapshot is deliberately *stale by default*: once a figure has come from
Console it keeps being used if a later refresh fails, because falling back to
an env rate on one failed GET would silently restate every charge of that
window. ``source`` records where the live figure came from so startup can
warn when it is only the fallback.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from typing import Optional

from src.config.env import SANDBOX_MARKUP_BPS, USD_TO_CREDITS_RATE

# Env fallbacks, resolved once. Kept separate from the live snapshot so a
# deployment can always say what its bare environment would charge.
ENV_USD_TO_CREDITS: float = float(USD_TO_CREDITS_RATE)
ENV_SANDBOX_MARKUP_BPS: int = int(SANDBOX_MARKUP_BPS)

SOURCE_CONSOLE = "console"
SOURCE_ENV = "env"

# How long a fetched snapshot is considered fresh. The refresher loop owns the
# renewal; readers only care that a figure exists, and stale beats env.
DEFAULT_TTL_SECONDS = 300.0


@dataclass(frozen=True)
class BillingRates:
    """One snapshot of the remotely-published billing settings."""

    usd_to_credits: float
    markup_bps: int
    source: str = SOURCE_ENV
    markup_source: str = SOURCE_ENV
    # The Console-published fx, kept even when the live rate is an env
    # fallback, so startup can report the disagreement instead of hiding it.
    console_fx: Optional[float] = None
    # Model names the public price book lists, in Console's own spelling.
    book_models: tuple[str, ...] = ()
    settings_version: Optional[str] = None
    fetched_at: Optional[float] = None
    expires_at: float = 0.0

    @property
    def from_console(self) -> bool:
        return self.source == SOURCE_CONSOLE

    def is_fresh(self, now: Optional[float] = None) -> bool:
        return bool(self.fetched_at) and (now or time.monotonic()) < self.expires_at


_lock = threading.Lock()
_cache: Optional[BillingRates] = None


def env_fallback() -> BillingRates:
    """The rates a bare environment would charge. Never preferred when a
    Console snapshot exists."""
    return BillingRates(
        usd_to_credits=ENV_USD_TO_CREDITS,
        markup_bps=ENV_SANDBOX_MARKUP_BPS,
        source=SOURCE_ENV,
        markup_source=SOURCE_ENV,
    )


def current() -> BillingRates:
    """The live snapshot, or the env fallback before the first fetch."""
    with _lock:
        snapshot = _cache
    return snapshot or env_fallback()


def snapshot() -> Optional[BillingRates]:
    """The last fetched snapshot, or None when Console has never answered."""
    with _lock:
        return _cache


def apply(rates: BillingRates, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> BillingRates:
    """Install a fetched snapshot and arm its freshness window."""
    now = time.monotonic()
    installed = replace(
        rates,
        fetched_at=now,
        expires_at=now + max(float(ttl_seconds), 0.0),
    )
    global _cache
    with _lock:
        _cache = installed
    return installed


def clear() -> None:
    """Drop the snapshot. Tests only; production never unlearns a price."""
    global _cache
    with _lock:
        _cache = None


def usd_to_credits_rate() -> float:
    """USD → credits for this deployment. Console first, env when never fetched."""
    return current().usd_to_credits


def sandbox_markup_bps() -> int:
    """Sandbox markup in basis points. Console first, env when never fetched."""
    return current().markup_bps


def console_model_name(model: str) -> str:
    """Spell a manifest model key the way the fetched price book does.

    The manifest keys names with hyphens (``claude-sonnet-5-5``) while Console
    and the relay use the dotted vendor spelling (``claude-sonnet-5.5``).
    Pricing one but not the other answers ``unknown_model``, which silently
    drops the turn onto the ``spent_usd`` fallback. A book that has not been
    fetched leaves the name untouched rather than guessing.
    """
    if not model:
        return model
    rates = current()
    if not rates.book_models:
        return model
    if model in rates.book_models:
        return model
    normalized = model.lower().replace(".", "-")
    for candidate in rates.book_models:
        if candidate.lower().replace(".", "-") == normalized:
            return candidate
    return model


__all__ = [
    "BillingRates",
    "DEFAULT_TTL_SECONDS",
    "ENV_SANDBOX_MARKUP_BPS",
    "ENV_USD_TO_CREDITS",
    "SOURCE_CONSOLE",
    "SOURCE_ENV",
    "apply",
    "clear",
    "console_model_name",
    "current",
    "env_fallback",
    "sandbox_markup_bps",
    "snapshot",
    "usd_to_credits_rate",
]
