"""The lease adapter's own decisions: what it sends, and what it does with an
answer it did not want.

Every one of these is a place where the honest move is to say nothing rather
than say something wrong — the gate keeps enforcing its last trusted verdict,
which is the whole fail-open promise.
"""

import asyncio

import pytest

from src.server.services import credit_gate_port as port_module
from src.server.services.credit_gate_port import PlatformCreditGatePort


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


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
    """Answers with a queued script; records what it was asked."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.posts: list[tuple] = []
        self.gets: list[tuple] = []

    def _next(self):
        return self.responses.pop(0) if self.responses else FakeResponse(200, {})

    async def post(self, url, json=None, headers=None, **kw):
        self.posts.append((url, json))
        return self._next()

    async def get(self, url, headers=None, **kw):
        self.gets.append((url, kw))
        return self._next()


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()

    async def _get_client():
        return fake

    monkeypatch.setattr(port_module.usage_limits, "get_http_client", _get_client)
    monkeypatch.setattr(port_module.usage_limits, "service_headers", lambda *a: {})
    monkeypatch.setattr(port_module.usage_limits, "service_token_missing", lambda: False)
    return fake


@pytest.fixture(autouse=True)
def settlement_db(monkeypatch):
    """No database in these tests: the release path's queue writes are recorded.

    ``credits`` is what the ledger's in-flight read answers; ``error`` makes it
    raise, which is the teardown that used to give the turn away.
    """
    state = {"credits": 0.0, "error": None}
    pending: list[tuple[str, str]] = []
    settled: list[tuple[str, object]] = []

    async def _in_flight(run_id):
        if state["error"] is not None:
            raise state["error"]
        return state["credits"]

    async def _mark_pending(run_id, reason):
        pending.append((run_id, reason))
        return True

    async def _mark_settled(run_id, *, charged_credits=None, detail=None):
        settled.append((run_id, charged_credits))
        return True

    monkeypatch.setattr(port_module.credit_ledger, "in_flight_credits", _in_flight)
    monkeypatch.setattr(port_module.settlement_db, "mark_settle_pending", _mark_pending)
    monkeypatch.setattr(port_module.settlement_db, "mark_settled", _mark_settled)
    return {"state": state, "pending": pending, "settled": settled}


@pytest.fixture
def no_sleep(monkeypatch):
    slept: list[float] = []

    async def _sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    return slept


# -- what we are willing to report ----------------------------------------


@pytest.mark.parametrize("spent", [float("nan"), float("inf"), 2_000_000.0])
@pytest.mark.asyncio
async def test_an_unreportable_spend_never_reaches_the_service(client, spent):
    """A number we do not believe is worse than no number: the gate keeps its
    last trusted verdict for a tick, and the next heartbeat corrects it."""
    assert await PlatformCreditGatePort().acquire("u", "run-1", spent) is None
    assert client.posts == []


@pytest.mark.parametrize("credits", [float("nan"), float("inf"), 2_000_000.0])
@pytest.mark.asyncio
async def test_an_unreportable_spend_never_reaches_the_ledger(monkeypatch, credits):
    """The beat is the write that has to hold the line. The ledger's write is
    monotone and Postgres ranks NaN above every real numeric, so one bad beat is
    permanent — no later correct value lowers it, and the per-user sum carries
    it to every other run that user has open."""
    wrote: list = []

    async def _heartbeat(kind, run_ref, value):
        wrote.append(value)
        return True

    monkeypatch.setattr(port_module.credit_ledger, "heartbeat", _heartbeat)
    assert await PlatformCreditGatePort().heartbeat("run", "r-1", credits) is None
    assert wrote == []


@pytest.mark.asyncio
async def test_a_believable_spend_reaches_the_ledger_and_its_answer_comes_back(
    monkeypatch,
):
    async def _heartbeat(kind, run_ref, value):
        return False

    monkeypatch.setattr(port_module.credit_ledger, "heartbeat", _heartbeat)
    assert await PlatformCreditGatePort().heartbeat("run", "r-1", 12.5) is False


@pytest.mark.asyncio
async def test_a_small_negative_is_clamped_rather_than_refused(client):
    client.responses = [FakeResponse(200, {"granted": True, "ceiling_credits": 5.0})]
    await PlatformCreditGatePort().acquire("u", "run-1", -0.0000001)
    assert client.posts[0][1]["spent_credits"] == 0.0


# -- the fence ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_grant_generation_is_carried_out_of_the_verdict(client):
    client.responses = [
        FakeResponse(200, {"granted": True, "ceiling_credits": 5.0, "generation": 9})
    ]
    verdict = await PlatformCreditGatePort().acquire("u", "run-1", 1.0)
    assert verdict.generation == 9


@pytest.mark.parametrize("raw", [True, "9", 9.5, None])
@pytest.mark.asyncio
async def test_a_generation_that_is_not_an_integer_leaves_the_release_unfenced(
    client, raw
):
    """Unfenced is the pre-fence behaviour, which is a worse race but a working
    release. A bogus fence would silently retire nothing at all."""
    client.responses = [
        FakeResponse(200, {"granted": True, "ceiling_credits": 5.0, "generation": raw})
    ]
    verdict = await PlatformCreditGatePort().acquire("u", "run-1", 1.0)
    assert verdict.generation is None


@pytest.mark.asyncio
async def test_release_sends_the_generation_only_when_it_has_one(client):
    await PlatformCreditGatePort().release("u", "run-1", 4)
    await PlatformCreditGatePort().release("u", "run-1")
    assert client.posts[0][1]["generation"] == 4
    assert "generation" not in client.posts[1][1]


# -- giving up on a release, and not too early ----------------------------


@pytest.mark.asyncio
async def test_release_retries_a_server_error_and_stops_on_success(
    client, no_sleep
):
    client.responses = [FakeResponse(503), FakeResponse(200, {"released": True})]
    await PlatformCreditGatePort().release("u", "run-1", 1)
    assert len(client.posts) == 2
    assert no_sleep == [0.5]


@pytest.mark.asyncio
async def test_release_does_not_retry_an_answer(client, no_sleep):
    """A 4xx is the service answering, 404 included — there was no lease, which
    is the idempotent case and not a failure."""
    client.responses = [FakeResponse(404)]
    await PlatformCreditGatePort().release("u", "run-1", 1)
    assert len(client.posts) == 1
    assert no_sleep == []


@pytest.mark.asyncio
async def test_release_gives_up_after_a_bounded_number_of_attempts(
    client, no_sleep
):
    client.responses = [FakeResponse(500) for _ in range(10)]
    await PlatformCreditGatePort().release("u", "run-1", 1)
    assert len(client.posts) == port_module._RELEASE_ATTEMPTS


@pytest.mark.asyncio
async def test_a_hanging_service_costs_one_timeout_not_three(
    client, no_sleep, monkeypatch
):
    """The attempt count bounds the tries, not the wait. This runs from the
    lane's teardown, so its total is what the user's stream waits out after
    output has already stopped."""
    now = [0.0]
    monkeypatch.setattr(port_module.time, "monotonic", lambda: now[0])

    async def hang(url, json=None, headers=None, timeout=None, **kw):
        client.posts.append((url, json))
        now[0] += timeout  # accepts the connection, then never answers
        raise TimeoutError("read timeout")

    monkeypatch.setattr(client, "post", hang)
    await PlatformCreditGatePort().release("u", "run-1", 1)

    assert len(client.posts) == 1
    assert now[0] == pytest.approx(port_module._RELEASE_BUDGET_SECONDS)


# -- the startup check ----------------------------------------------------


@pytest.mark.asyncio
async def test_capability_reports_nothing_when_the_route_is_not_there(client):
    client.responses = [FakeResponse(404, text="Not Found")]
    assert await PlatformCreditGatePort().capability() is None


@pytest.mark.asyncio
async def test_the_wiring_check_is_silent_without_platform_gating(
    client, monkeypatch
):
    """OSS builds have no service to ask, and a boot-time GET at a URL that
    means nothing to them is noise, not a check."""
    monkeypatch.setattr(port_module.usage_limits, "platform_gating_active", lambda: False)
    await port_module.verify_credit_gate_wiring()
    assert client.gets == []


@pytest.mark.parametrize(
    "ttl", [port_module.LEASE_RENEW_MARGIN_SECONDS, 30, port_module.LEASE_RENEW_MARGIN_SECONDS + 1]
)
@pytest.mark.asyncio
async def test_the_wiring_check_never_raises_on_any_ttl(client, monkeypatch, ttl):
    """It runs inside the lifespan. Whatever it finds, the server still boots —
    the gate is an extra guard, not an availability dependency."""
    monkeypatch.setattr(port_module.usage_limits, "platform_gating_active", lambda: True)
    monkeypatch.setattr(
        port_module.console_rates,
        "ensure_console_rates",
        _async_return(_console_rates()),
    )
    client.responses = [FakeResponse(200, {"enabled": True, "lease_ttl_seconds": ttl})]
    await port_module.verify_credit_gate_wiring()
    assert len(client.gets) == 1


# -- what the reservation is sized in -------------------------------------


@pytest.mark.asyncio
async def test_the_rate_reaches_the_service(client):
    client.responses = [FakeResponse(200, {"granted": True, "ceiling_credits": 5.0})]
    await PlatformCreditGatePort().acquire("u", "run-1", 1.0, 8.5)
    assert client.posts[0][1]["rate_multiplier"] == 8.5


@pytest.mark.asyncio
async def test_the_billing_source_reaches_the_service(client):
    """Admission forwards it, so the lease must too: the service folds the same
    billing row for both, and without this it answers the run's own admission
    verdict with the opposite one."""
    client.responses = [
        FakeResponse(200, {"granted": True, "ceiling_credits": 5.0}),
        FakeResponse(200, {"granted": True, "ceiling_credits": 5.0}),
    ]
    await PlatformCreditGatePort().acquire("u", "run-1", 1.0, 1.0, True)
    assert client.posts[0][1]["byok"] is True

    # Absent, not false, for a platform-funded turn: the payload a service that
    # has never heard of the field still reads exactly as it did before.
    await PlatformCreditGatePort().acquire("u", "run-1", 1.0)
    assert "byok" not in client.posts[1][1]


@pytest.mark.parametrize(
    "sent, expected",
    [
        (0.0, port_module._MIN_RATE_MULTIPLIER),
        (1e9, port_module._MAX_RATE_MULTIPLIER),
        (float("nan"), 1.0),
        (float("inf"), 1.0),
        (None, 1.0),
        ("eight", 1.0),
    ],
)
@pytest.mark.asyncio
async def test_a_rate_we_cannot_use_is_clamped_not_refused(client, sent, expected):
    """Unlike an unreportable spend, a bad rate never withholds the ask. The
    spend is the figure the verdict is computed from, so a wrong one is worse
    than none; the rate only sizes the headroom, and the honest fallback is to
    ask at the baseline rather than leave the turn without a ceiling."""
    client.responses = [FakeResponse(200, {"granted": True, "ceiling_credits": 5.0})]
    await PlatformCreditGatePort().acquire("u", "run-1", 1.0, sent)
    assert client.posts[0][1]["rate_multiplier"] == expected


@pytest.mark.asyncio
async def test_an_unpriced_model_reserves_at_the_baseline(monkeypatch):
    """A model the manifest cannot price leaves the reservation where it was,
    which is the same thing every OSS build gets."""
    monkeypatch.setattr(port_module.usage_limits, "platform_gating_active", lambda: True)
    gate = port_module.build_run_credit_gate(
        "u", "run-1", None, None, "not-a-real-model-anywhere"
    )
    assert gate.rate_multiplier == 1.0


# -- the numbers the service publishes so this build can check them --------


def test_ttl_prefers_the_service_differenced_remainder():
    """Skew lives entirely in the subtraction. ``expires_in_seconds`` is
    differenced on one clock, so a stamp this host reads as long past still
    yields the real remaining TTL."""
    body = {"expires_at": "2000-01-01T00:00:00+00:00", "expires_in_seconds": 300}
    assert port_module._ttl_seconds(body) == 300.0


def test_ttl_falls_back_to_the_stamp_then_to_the_stand_in():
    assert port_module._ttl_seconds({"expires_at": "2000-01-01T00:00:00+00:00"}) == 0.0
    assert port_module._ttl_seconds({}) == port_module._UNKNOWN_TTL_SECONDS


@pytest.mark.asyncio
async def test_the_wiring_check_reports_a_bounds_disagreement(
    client, monkeypatch, caplog
):
    """A multiplier the service rejects comes back 422, which reads as no
    verdict and leaves the turn ungated. Boot is the only place that can see
    that coming."""
    monkeypatch.setattr(
        port_module.usage_limits, "platform_gating_active", lambda: True
    )
    monkeypatch.setattr(
        port_module.console_rates,
        "ensure_console_rates",
        _async_return(_console_rates()),
    )
    client.responses = [
        FakeResponse(
            200,
            {
                "enabled": True,
                "lease_ttl_seconds": port_module.LEASE_RENEW_MARGIN_SECONDS + 60,
                "rate_multiplier_min": port_module._MIN_RATE_MULTIPLIER * 5,
                "rate_multiplier_max": port_module._MAX_RATE_MULTIPLIER,
            },
        )
    ]
    with caplog.at_level("ERROR"):
        await port_module.verify_credit_gate_wiring()
    assert "bounds disagree" in caplog.text


def _console_rates(**overrides):
    """A console-published snapshot for the wiring check's rate leg."""
    from src.config.billing_rates import (
        ENV_SANDBOX_MARKUP_BPS,
        ENV_USD_TO_CREDITS,
        SOURCE_CONSOLE,
        BillingRates,
    )

    fields = {
        "usd_to_credits": ENV_USD_TO_CREDITS,
        "markup_bps": ENV_SANDBOX_MARKUP_BPS,
        "source": SOURCE_CONSOLE,
        "markup_source": SOURCE_CONSOLE,
        "console_fx": ENV_USD_TO_CREDITS,
    }
    fields.update(overrides)
    return BillingRates(**fields)


@pytest.mark.asyncio
async def test_the_wiring_check_is_quiet_when_the_bounds_agree(
    client, monkeypatch, caplog
):
    monkeypatch.setattr(
        port_module.usage_limits, "platform_gating_active", lambda: True
    )
    monkeypatch.setattr(
        port_module.console_rates,
        "ensure_console_rates",
        _async_return(_console_rates()),
    )
    client.responses = [
        FakeResponse(
            200,
            {
                "enabled": True,
                "lease_ttl_seconds": port_module.LEASE_RENEW_MARGIN_SECONDS + 60,
                "rate_multiplier_min": port_module._MIN_RATE_MULTIPLIER,
                "rate_multiplier_max": port_module._MAX_RATE_MULTIPLIER,
            },
        )
    ]
    with caplog.at_level("ERROR"):
        await port_module.verify_credit_gate_wiring()
    assert "bounds disagree" not in caplog.text
    assert "fx.usd_to_credits was not read" not in caplog.text


@pytest.mark.asyncio
async def test_the_wiring_check_reports_unpublished_fx(client, monkeypatch, caplog):
    """The old check compared env against a hard-coded canonical unit, so it
    fired on every correctly configured deployment. The failure that matters
    now is a platform deployment whose rate the console never published: its
    ledger cannot be reconciled against anything."""
    from src.config.billing_rates import env_fallback

    monkeypatch.setattr(
        port_module.usage_limits, "platform_gating_active", lambda: True
    )
    monkeypatch.setattr(
        port_module.console_rates,
        "ensure_console_rates",
        _async_return(env_fallback()),
    )
    client.responses = [
        FakeResponse(
            200,
            {
                "enabled": True,
                "lease_ttl_seconds": port_module.LEASE_RENEW_MARGIN_SECONDS + 60,
            },
        )
    ]
    with caplog.at_level("ERROR"):
        await port_module.verify_credit_gate_wiring()
    assert "fx.usd_to_credits was not read" in caplog.text


@pytest.mark.asyncio
async def test_the_wiring_check_reports_an_env_rate_that_disagrees(
    client, monkeypatch, caplog
):
    monkeypatch.setattr(
        port_module.usage_limits, "platform_gating_active", lambda: True
    )
    monkeypatch.setattr(
        port_module.console_rates,
        "ensure_console_rates",
        _async_return(_console_rates(console_fx=680.0, usd_to_credits=680.0)),
    )
    client.responses = [
        FakeResponse(
            200,
            {
                "enabled": True,
                "lease_ttl_seconds": port_module.LEASE_RENEW_MARGIN_SECONDS + 60,
            },
        )
    ]
    with caplog.at_level("WARNING"):
        await port_module.verify_credit_gate_wiring()
    assert "console publishes fx=680" in caplog.text


# -- what the release reports ---------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_rates():
    """The rates snapshot is process-global; a rate one test installs must not
    price the next one."""
    from src.config import billing_rates

    billing_rates.clear()
    yield
    billing_rates.clear()


def _settlement(**overrides):
    from src.utils.tracking.model_usage import ReleaseSettlement

    fields = {
        "model_usage": [
            {
                "model": "claude-sonnet-5-5",
                "input": 1000,
                "output": 200,
                "cache_read": 0,
                "cache_write": 0,
                "calls": 2,
            }
        ],
        "spent_usd": 0.0123,
        "byok": False,
        "has_records": True,
        "call_count": 2,
    }
    fields.update(overrides)
    return ReleaseSettlement(**fields)


@pytest.mark.asyncio
async def test_release_sends_model_usage_and_respells_it_for_the_book(client):
    """The manifest keys hyphens, the console's book keys dots. Sending the
    manifest spelling answers unknown_model and silently lands the turn on the
    scalar fallback, which is exactly the same-price failure this fixes."""
    from src.config import billing_rates

    billing_rates.apply(
        billing_rates.BillingRates(
            usd_to_credits=720,
            markup_bps=13000,
            source=billing_rates.SOURCE_CONSOLE,
            markup_source=billing_rates.SOURCE_CONSOLE,
            console_fx=720,
            book_models=("claude-sonnet-5.5",),
        )
    )

    await PlatformCreditGatePort().release(
        "u", "run-1", 3, _settlement()
    )

    payload = client.posts[0][1]
    assert payload["model_usage"] == [
        {
            "model": "claude-sonnet-5.5",
            "input": 1000,
            "output": 200,
            "cache_read": 0,
            "cache_write": 0,
            "calls": 2,
        }
    ]
    assert payload["spent_usd"] == 0.0123


@pytest.mark.asyncio
async def test_release_falls_back_to_the_in_flight_figure_without_usage(
    client, settlement_db
):
    settlement_db["state"]["credits"] = 7.5
    await PlatformCreditGatePort().release("u", "run-1", 1)

    assert client.posts[0][1]["spent_credits"] == 7.5
    assert "model_usage" not in client.posts[0][1]
    assert settlement_db["pending"] == []


@pytest.mark.asyncio
async def test_an_unreadable_ledger_with_no_usage_is_not_released(
    client, settlement_db
):
    """Releasing with no figure retires the whole reserved ceiling and gives
    the turn away. The lease is left to stand and the run queued instead."""
    settlement_db["state"]["error"] = RuntimeError("pool exhausted")
    await PlatformCreditGatePort().release("u", "run-1", 1)

    assert client.posts == []
    assert settlement_db["pending"]
    assert settlement_db["pending"][0][0] == "run-1"
    assert "in_flight_credits unreadable" in settlement_db["pending"][0][1]


@pytest.mark.asyncio
async def test_its_own_usage_settles_even_when_the_ledger_is_unreadable(
    client, settlement_db
):
    """The tracker's figure is a real spend record; only its absence needs the
    queue."""
    settlement_db["state"]["error"] = RuntimeError("pool exhausted")
    await PlatformCreditGatePort().release("u", "run-1", 1, _settlement())

    assert client.posts[0][1]["model_usage"]
    assert settlement_db["pending"] == []


@pytest.mark.asyncio
async def test_byok_travels_on_the_release_and_never_on_a_platform_turn(
    client, settlement_db
):
    await PlatformCreditGatePort().release(
        "u", "run-1", 1, _settlement(byok=True, model_usage=[], has_records=False)
    )
    await PlatformCreditGatePort().release("u", "run-2", 1, _settlement())

    assert client.posts[0][1]["byok"] is True
    assert "byok" not in client.posts[1][1]


@pytest.mark.asyncio
async def test_a_release_that_never_lands_is_queued_for_settlement(
    client, settlement_db, no_sleep
):
    client.responses = [FakeResponse(500) for _ in range(10)]
    await PlatformCreditGatePort().release("u", "run-1", 1, _settlement())

    assert len(client.posts) == port_module._RELEASE_ATTEMPTS
    assert settlement_db["pending"]
    assert "release failed" in settlement_db["pending"][0][1]


@pytest.mark.asyncio
async def test_a_successful_release_records_the_console_charge(
    client, settlement_db, caplog
):
    """charged_credits is the only priced figure a model_usage release has;
    stamping it is what makes the run reconcilable against the ledger."""
    client.responses = [FakeResponse(200, {"released": True, "charged_credits": 900})]
    with caplog.at_level("WARNING"):
        await PlatformCreditGatePort().release(
            "u", "run-1", 1, _settlement(spent_usd=0.0123)
        )

    # 0.0123 * 720 ≈ 8.9 credits against a charged 900: the paths disagree.
    assert "off the spent_usd estimate" in caplog.text
    assert settlement_db["settled"] == [("run-1", 900)]


@pytest.mark.asyncio
async def test_a_fallback_answer_is_reported(client, caplog):
    client.responses = [
        FakeResponse(200, {"released": True, "fallback": True, "charged_credits": 9})
    ]
    with caplog.at_level("WARNING"):
        await PlatformCreditGatePort().release("u", "run-1", 1, _settlement())
    assert "fell back to the scalar" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 409])
async def test_an_already_retired_lease_is_an_answer(
    client, settlement_db, status
):
    """404 is "no lease to retire" and 409 is "already settled" — both are the
    idempotent case, not a failure, and both stamp the run settled."""
    client.responses = [FakeResponse(status, text="gone")]
    await PlatformCreditGatePort().release("u", "run-1", 1, _settlement())

    assert len(client.posts) == 1
    assert settlement_db["pending"] == []
    assert settlement_db["settled"]


@pytest.mark.asyncio
async def test_a_top_up_answer_keeps_the_run_queued(client, settlement_db):
    """402 is a wallet state, not a report the console refuses: the lease is
    still standing, so the run must be settled later rather than dropped."""
    client.responses = [
        FakeResponse(402, text="insufficient credits")
        for _ in range(port_module._RELEASE_ATTEMPTS)
    ]
    await PlatformCreditGatePort().release("u", "run-1", 1, _settlement())

    assert settlement_db["pending"]
    assert "release failed" in settlement_db["pending"][0][1]


@pytest.mark.asyncio
async def test_a_refusal_nothing_can_change_leaves_the_queue(client, settlement_db):
    client.responses = [FakeResponse(422, text="unknown_model")]
    await PlatformCreditGatePort().release("u", "run-1", 1, _settlement())

    assert settlement_db["pending"] == []
    assert settlement_db["settled"]
