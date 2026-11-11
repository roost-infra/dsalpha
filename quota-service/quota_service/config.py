"""Environment configuration for the quota service."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    database_url: str
    internal_service_token: str
    admin_token: str
    default_plan: str = "free"
    per_turn_credits: float = 500.0
    lease_ttl_seconds: int = 300
    allow_negative_balance: bool = False
    monthly_grant_tz: str = "Asia/Shanghai"
    auto_migrate: bool = True
    ingest_enabled: bool = True
    ingest_interval_seconds: int = 60
    sandbox_default_per_hour: float = 166.7  # credits/h fallback for unpriced tiers
    host: str = "0.0.0.0"
    port: int = 8080
    cookie_max_age_seconds: int = 8 * 3600

    @property
    def cookie_secret(self) -> str:
        # A rotated ADMIN_TOKEN invalidates every admin session too, which is
        # the behaviour an operator expects from the emergency credential.
        return self.admin_token


def load_settings() -> Settings:
    """Read the environment once, failing fast on the credentials we cannot invent."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    internal = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
    if not internal:
        raise RuntimeError("INTERNAL_SERVICE_TOKEN is required (shared with dsalpha)")
    admin = os.getenv("ADMIN_TOKEN", "").strip()
    if not admin:
        raise RuntimeError("ADMIN_TOKEN is required (admin page and admin API)")
    return Settings(
        database_url=database_url,
        internal_service_token=internal,
        admin_token=admin,
        default_plan=os.getenv("DEFAULT_PLAN", "free").strip() or "free",
        per_turn_credits=_float("PER_TURN_CREDITS", 500.0),
        lease_ttl_seconds=_int("LEASE_TTL_SECONDS", 300),
        allow_negative_balance=_bool("ALLOW_NEGATIVE_BALANCE", False),
        monthly_grant_tz=os.getenv("MONTHLY_GRANT_TZ", "Asia/Shanghai").strip()
        or "Asia/Shanghai",
        auto_migrate=_bool("QUOTA_AUTO_MIGRATE", True),
        ingest_enabled=_bool("INGEST_ENABLED", True),
        ingest_interval_seconds=_int("INGEST_INTERVAL_SECONDS", 60),
        sandbox_default_per_hour=_float("SANDBOX_DEFAULT_CREDITS_PER_HOUR", 166.7),
        host=os.getenv("HOST", "0.0.0.0"),
        port=_int("PORT", 8080),
        cookie_max_age_seconds=_int("ADMIN_COOKIE_MAX_AGE", 8 * 3600),
    )
