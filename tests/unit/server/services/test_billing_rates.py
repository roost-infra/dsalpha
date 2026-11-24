"""Console-sourced billing settings: one rate fact, one fallback.

The properties pinned here are the migration's whole point: fx and markup come
from the console's settings, the fallback is only for a deployment that has
never been answered, a previously fetched snapshot survives an outage (a
failed GET must not silently restate charges at the env rate), and model names
are respelled to the book's own spelling before they reach pricing.
"""

from __future__ import annotations

import pytest

from src.config import billing_rates as cache
from src.config.env import SANDBOX_MARKUP_BPS, USD_TO_CREDITS_RATE
from src.server.services import billing_rates as rates


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class FakeClient:
    """Answers GETs from a script keyed by path; records the paths asked."""

    def __init__(self, answers=None, error: Exception | None = None):
        self.answers = dict(answers or {})
        self.error = error
        self.gets: list[str] = []

    async def get(self, url, headers=None, timeout=None):
        from urllib.parse import urlsplit

        path = urlsplit(url).path
        if path.startswith("/console-api"):
            path = path[len("/console-api") :]
        self.gets.append(path)
        if self.error is not None:
            raise self.error
        return self.answers.get(path, FakeResponse(404))


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    cache.clear()
    monkeypatch.setattr(rates, "_markup_fallback_logged", False)
    monkeypatch.setattr(rates, "AUTH_SERVICE_URL", "https://console.test/console-api")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "service-secret")
    monkeypatch.setattr(rates.usage_limits, "service_token_missing", lambda: False)
    monkeypatch.setattr(
        rates.usage_limits, "signed_service_headers", lambda *a, **k: {}
    )
    yield
    cache.clear()


# -- parsing ----------------------------------------------------------------


def test_fx_is_read_from_the_contract_shape():
    assert rates.fx_from_book({"fx": {"usd_to_credits": 720}}) == 720
    assert rates.fx_from_book({"fx.usd_to_credits": 680}) == 680
    assert rates.fx_from_book({"fx": {"usd_to_credits": 0}}) is None
    assert rates.fx_from_book({"fx": {"usd_to_credits": "nan"}}) is None
    assert rates.fx_from_book({}) is None
    assert rates.fx_from_book(None) is None


def test_markup_is_read_in_every_shape_the_console_may_publish():
    assert rates.markup_bps_from_body({"sandbox.markup_bps": 13000}) == 13000
    assert rates.markup_bps_from_body({"sandbox": {"markup_bps": 13000}}) == 13000
    assert (
        rates.markup_bps_from_body({"settings": {"sandbox.markup_bps": 13000}})
        == 13000
    )
    assert rates.markup_bps_from_body({"data": {"sandbox": {"markup_bps": 13000}}}) == 13000
    assert rates.markup_bps_from_body({"markup_bps": 13000}) == 13000
    assert rates.markup_bps_from_body({"sandbox.markup_bps": 0}) is None
    assert rates.markup_bps_from_body({}) is None


def test_model_names_come_from_the_public_book():
    body = {
        "models": [
            {"model": "claude-sonnet-5.5"},
            {"model": "gpt-6-astra"},
            {"model": 7},
            {"not": "a model"},
        ]
    }
    assert rates.model_names_from_book(body) == ("claude-sonnet-5.5", "gpt-6-astra")
    assert rates.model_names_from_book({"models": "nope"}) == ()


# -- fetching ---------------------------------------------------------------


PUBLIC_BOOK = {
    "version": "2026-11-25.1",
    "fx": {"usd_to_credits": 720, "credit_yuan": 0.01},
    "models": [{"model": "claude-sonnet-5.5"}],
}
INTERNAL_BOOK = {
    "version": "2026-11-25.1",
    "fx": {"usd_to_credits": 720},
    "sandbox": {"markup_bps": 13000},
}


@pytest.mark.asyncio
async def test_fetch_reads_fx_from_the_public_book_and_markup_from_the_internal_one():
    client = FakeClient(
        {
            rates.BOOK_PATH: FakeResponse(200, PUBLIC_BOOK),
            rates.INTERNAL_BOOK_PATH: FakeResponse(200, INTERNAL_BOOK),
        }
    )
    fetched = await rates.fetch_billing_rates(client=client)

    assert fetched.usd_to_credits == 720
    assert fetched.source == cache.SOURCE_CONSOLE
    assert fetched.markup_bps == 13000
    assert fetched.markup_source == cache.SOURCE_CONSOLE
    assert fetched.console_fx == 720
    assert fetched.book_models == ("claude-sonnet-5.5",)
    assert fetched.settings_version == "2026-11-25.1"
    # The public book first, then the service-authenticated one.
    assert client.gets[:2] == [rates.BOOK_PATH, rates.INTERNAL_BOOK_PATH]


@pytest.mark.asyncio
async def test_a_console_that_names_no_fx_falls_back_to_env():
    client = FakeClient(
        {
            rates.BOOK_PATH: FakeResponse(200, {"models": []}),
            rates.INTERNAL_BOOK_PATH: FakeResponse(404),
            rates.SETTINGS_PATHS[0]: FakeResponse(200, {"sandbox.markup_bps": 13000}),
        }
    )
    fetched = await rates.fetch_billing_rates(client=client)

    assert fetched.usd_to_credits == USD_TO_CREDITS_RATE
    assert fetched.source == cache.SOURCE_ENV
    assert fetched.console_fx is None
    assert fetched.markup_bps == 13000
    assert fetched.markup_source == cache.SOURCE_CONSOLE


@pytest.mark.asyncio
async def test_a_console_that_publishes_no_markup_uses_the_env_rate(caplog):
    client = FakeClient(
        {
            rates.BOOK_PATH: FakeResponse(200, PUBLIC_BOOK),
            rates.INTERNAL_BOOK_PATH: FakeResponse(200, {"version": "x"}),
            rates.SETTINGS_PATHS[0]: FakeResponse(404),
            rates.SETTINGS_PATHS[1]: FakeResponse(404),
        }
    )
    with caplog.at_level("WARNING"):
        fetched = await rates.fetch_billing_rates(client=client)

    assert fetched.markup_bps == SANDBOX_MARKUP_BPS
    assert fetched.markup_source == cache.SOURCE_ENV
    assert "names no sandbox.markup_bps" in caplog.text


# -- cache and fallback -----------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_installs_the_snapshot_and_stamps_its_window(monkeypatch):
    monkeypatch.setattr(rates.usage_limits, "platform_gating_active", lambda: True)
    client = FakeClient(
        {
            rates.BOOK_PATH: FakeResponse(200, PUBLIC_BOOK),
            rates.INTERNAL_BOOK_PATH: FakeResponse(200, INTERNAL_BOOK),
        }
    )
    installed = await rates.refresh_billing_rates(client=client)

    assert cache.current() == installed
    assert installed.is_fresh()
    assert cache.usd_to_credits_rate() == 720
    assert cache.sandbox_markup_bps() == 13000


@pytest.mark.asyncio
async def test_a_later_outage_keeps_the_last_published_rate(monkeypatch):
    """One failed GET must not move the rate back to env: that would silently
    restate every charge of the window at a different price."""
    monkeypatch.setattr(rates.usage_limits, "platform_gating_active", lambda: True)
    good = FakeClient(
        {
            rates.BOOK_PATH: FakeResponse(200, PUBLIC_BOOK),
            rates.INTERNAL_BOOK_PATH: FakeResponse(200, INTERNAL_BOOK),
        }
    )
    await rates.refresh_billing_rates(client=good)

    failed = FakeClient(error=TimeoutError("read timeout"))
    kept = await rates.refresh_billing_rates(client=failed)

    assert kept.usd_to_credits == 720
    assert kept.source == cache.SOURCE_CONSOLE
    assert cache.snapshot() is not None


@pytest.mark.asyncio
async def test_an_unanswered_console_uses_env_and_never_raises(monkeypatch, caplog):
    monkeypatch.setattr(rates.usage_limits, "platform_gating_active", lambda: True)
    failed = FakeClient(error=RuntimeError("connection refused"))
    with caplog.at_level("WARNING"):
        installed = await rates.refresh_billing_rates(client=failed)

    assert installed.usd_to_credits == USD_TO_CREDITS_RATE
    assert installed.markup_bps == SANDBOX_MARKUP_BPS
    assert installed.source == cache.SOURCE_ENV
    assert "published no usable fx.usd_to_credits" in caplog.text


@pytest.mark.asyncio
async def test_missing_service_token_skips_the_authenticated_fetch(monkeypatch):
    monkeypatch.setattr(rates.usage_limits, "platform_gating_active", lambda: True)
    monkeypatch.setattr(rates.usage_limits, "service_token_missing", lambda: True)
    client = FakeClient()
    installed = await rates.refresh_billing_rates(client=client)

    assert installed.source == cache.SOURCE_ENV
    assert client.gets == []


@pytest.mark.asyncio
async def test_ensure_console_rates_reuses_a_fresh_snapshot(monkeypatch):
    monkeypatch.setattr(rates.usage_limits, "platform_gating_active", lambda: True)
    client = FakeClient(
        {
            rates.BOOK_PATH: FakeResponse(200, PUBLIC_BOOK),
            rates.INTERNAL_BOOK_PATH: FakeResponse(200, INTERNAL_BOOK),
        }
    )
    await rates.refresh_billing_rates(client=client)
    calls = len(client.gets)

    again = await rates.ensure_console_rates(client=client)
    assert again.source == cache.SOURCE_CONSOLE
    assert len(client.gets) == calls


@pytest.mark.asyncio
async def test_ensure_console_rates_without_platform_gating_never_calls(
    monkeypatch,
):
    monkeypatch.setattr(rates.usage_limits, "platform_gating_active", lambda: False)
    client = FakeClient()
    installed = await rates.ensure_console_rates(client=client)
    assert installed.source == cache.SOURCE_ENV
    assert client.gets == []


def test_an_env_fallback_snapshot_keeps_the_console_figure_when_it_has_one():
    snapshot = cache.BillingRates(
        usd_to_credits=720,
        markup_bps=13000,
        source=cache.SOURCE_CONSOLE,
        markup_source=cache.SOURCE_CONSOLE,
        console_fx=720,
    )
    assert snapshot.from_console is True
    assert cache.BillingRates(usd_to_credits=1, markup_bps=1).from_console is False


# -- model spelling ---------------------------------------------------------


def test_a_manifest_key_is_respelled_to_the_book_name():
    cache.apply(
        cache.BillingRates(
            usd_to_credits=720,
            markup_bps=13000,
            source=cache.SOURCE_CONSOLE,
            book_models=("claude-sonnet-5.5", "gpt-6-astra"),
        )
    )
    assert cache.console_model_name("claude-sonnet-5-5") == "claude-sonnet-5.5"
    assert cache.console_model_name("gpt-6-astra") == "gpt-6-astra"
    assert cache.console_model_name("unknown-model") == "unknown-model"


def test_without_a_fetched_book_names_are_left_alone():
    assert cache.console_model_name("claude-sonnet-5-5") == "claude-sonnet-5-5"
    assert cache.console_model_name("") == ""


@pytest.mark.asyncio
async def test_a_missing_markup_keeps_the_last_published_one(monkeypatch):
    """Half the settings surface vanishing must not move sandbox pricing onto
    the env fallback while fx still answers."""
    monkeypatch.setattr(rates.usage_limits, "platform_gating_active", lambda: True)
    first = FakeClient(
        {
            rates.BOOK_PATH: FakeResponse(200, PUBLIC_BOOK),
            rates.INTERNAL_BOOK_PATH: FakeResponse(200, INTERNAL_BOOK),
        }
    )
    await rates.refresh_billing_rates(client=first)

    second = FakeClient(
        {
            rates.BOOK_PATH: FakeResponse(200, PUBLIC_BOOK),
            rates.INTERNAL_BOOK_PATH: FakeResponse(404),
            rates.SETTINGS_PATHS[0]: FakeResponse(404),
            rates.SETTINGS_PATHS[1]: FakeResponse(404),
        }
    )
    installed = await rates.refresh_billing_rates(client=second)

    assert installed.usd_to_credits == 720
    assert installed.markup_bps == 13000
    assert installed.markup_source == cache.SOURCE_CONSOLE


def test_the_billing_settings_route_is_tried_first():
    assert rates.SETTINGS_PATHS[0] == "/internal/v1/billing/settings"


@pytest.mark.asyncio
async def test_flat_settings_can_supply_both_figures():
    """Console's settings surface carries flat keys; it may be the only place
    they are exposed, so fx must be read from it as well as from the book."""
    client = FakeClient(
        {
            rates.BOOK_PATH: FakeResponse(404),
            rates.INTERNAL_BOOK_PATH: FakeResponse(404),
            "/internal/v1/billing/settings": FakeResponse(
                200,
                {"sandbox.markup_bps": 13000, "fx.usd_to_credits": 680},
            ),
        }
    )
    fetched = await rates.fetch_billing_rates(client=client)

    assert fetched.usd_to_credits == 680
    assert fetched.source == cache.SOURCE_CONSOLE
    assert fetched.markup_bps == 13000
    assert fetched.markup_source == cache.SOURCE_CONSOLE
    assert "/internal/v1/billing/settings" in client.gets
