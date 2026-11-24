"""Sandbox billing: the price, the wire body, and every answer that decides a
run's fate.

The console's own validation is pinned in the console repository; these tests
pin what this side sends and which answers leave a run queued instead of
settled. The pricing cases start with the contract's worked example: one
vCPU, one GiB and five GiB of disk for an hour is 63 credits at the
production rate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.server.services import sandbox_billing as billing
from src.server.services.sandbox_billing import (
    SandboxPrices,
    build_usage_body,
    compute_charge,
    idempotency_key,
    report_closed_runs,
    report_once,
    resolve_org,
)

ORG_ID = "11111111-1111-1111-1111-111111111111"
RUN_ID = "22222222-2222-2222-2222-222222222222"
COMPUTER_ID = "33333333-3333-3333-3333-333333333333"
USER_ID = "44444444-4444-4444-4444-444444444444"
T0 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
PRICES = SandboxPrices()
MARKUP_BPS = 13000
USD_TO_CREDITS = 720


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
    """Answers with a queued script; records the bytes and headers it got."""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.posts: list[tuple[str, bytes, dict]] = []

    async def post(self, url, content=None, headers=None):
        self.posts.append((url, content, dict(headers or {})))
        return self.responses.pop(0) if self.responses else FakeResponse(201, {})


def _run(**overrides):
    run = {
        "run_id": RUN_ID,
        "computer_id": COMPUTER_ID,
        "user_id": USER_ID,
        "provider_kind": "daytona",
        "provider_sandbox_id": "sbx-1",
        "cpu": 1.0,
        "memory_gb": 1.0,
        "disk_gb": 5.0,
        "started_at": T0,
        "ended_at": T0 + timedelta(hours=1),
        "billing_reported_at": None,
    }
    run.update(overrides)
    return run


@pytest.fixture
def marks(monkeypatch):
    billed = AsyncMock(return_value=True)
    error = AsyncMock(return_value=True)
    monkeypatch.setattr(billing.runs_db, "mark_run_billed", billed)
    monkeypatch.setattr(billing.runs_db, "mark_run_billing_error", error)
    return billed, error


@pytest.fixture
def console(monkeypatch):
    monkeypatch.setattr(billing, "AUTH_SERVICE_URL", "https://console.test/console-api")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "service-secret")
    return FakeClient()


async def _attempt(run, client, *, org_cache=None):
    return await billing._attempt_run(
        run,
        client=client,
        org_cache={USER_ID: ORG_ID} if org_cache is None else org_cache,
        org_failures={},
        prices=PRICES,
        markup_bps=MARKUP_BPS,
        usd_to_credits=USD_TO_CREDITS,
    )


# -- pricing ----------------------------------------------------------------


def test_the_contract_example_is_63_credits():
    charge = compute_charge(1, 1, 5, 3600, MARKUP_BPS, USD_TO_CREDITS)
    assert charge.total_credits == 63
    assert charge.cpu_credits == 47.1744
    assert charge.memory_credits == 15.1632
    assert charge.disk_credits == 0.0
    assert charge.billable_seconds == 3600
    assert charge.cpu_seconds == 3600
    assert charge.memory_mib_seconds == 1024 * 3600


def test_the_first_five_gib_of_disk_are_free_and_the_rest_is_priced():
    free = compute_charge(0, 0, 5, 3600, MARKUP_BPS, USD_TO_CREDITS)
    over = compute_charge(0, 0, 6, 3600, MARKUP_BPS, USD_TO_CREDITS)

    assert free.disk_billable_gb == 0.0
    assert free.total_credits == 1  # usage is positive even when the sum is 0
    assert over.disk_billable_gb == 1.0
    assert over.disk_credits == 0.1011


def test_the_markup_scales_every_component():
    base = compute_charge(2, 4, 10, 3600, 10000, USD_TO_CREDITS)
    marked = compute_charge(2, 4, 10, 3600, MARKUP_BPS, USD_TO_CREDITS)

    assert marked.cpu_credits == pytest.approx(base.cpu_credits * 1.3, abs=1e-4)
    assert marked.memory_credits == pytest.approx(base.memory_credits * 1.3, abs=1e-4)
    assert marked.disk_credits == pytest.approx(base.disk_credits * 1.3, abs=1e-4)


def test_the_total_is_the_ceiling_of_the_unrounded_components():
    charge = compute_charge(2, 4, 100, 3600, MARKUP_BPS, USD_TO_CREDITS)
    summed = charge.cpu_credits + charge.memory_credits + charge.disk_credits
    assert charge.total_credits == 165
    assert charge.total_credits == int(-(-summed // 1))


@pytest.mark.parametrize(
    "args",
    [
        (0, 0, 0, 0),
        (1, 1, 5, 0),
        (0, 0, 0, 3600),
    ],
)
def test_no_usage_no_charge(args):
    assert compute_charge(*args, MARKUP_BPS, USD_TO_CREDITS).total_credits == 0


@pytest.mark.parametrize(
    "args",
    [
        (-1, 1, 5, 3600),
        (1, -1, 5, 3600),
        (1, 1, 5, -1),
        (float("nan"), 1, 5, 3600),
        (1, 1, 5, float("inf")),
    ],
)
def test_an_unbelievable_resource_is_refused(args):
    with pytest.raises(ValueError):
        compute_charge(*args, MARKUP_BPS, USD_TO_CREDITS)


# -- the body ---------------------------------------------------------------


def test_the_body_carries_the_console_contract_and_a_stable_key():
    charge = compute_charge(2, 4, 100, 3600, MARKUP_BPS, USD_TO_CREDITS)
    body = build_usage_body(
        _run(),
        ORG_ID,
        charge,
        prices=PRICES,
        markup_bps=MARKUP_BPS,
        usd_to_credits=USD_TO_CREDITS,
    )

    assert body["org_id"] == ORG_ID
    assert body["user_id"] == USER_ID
    assert body["product"] == "dsalpha"
    assert body["sandbox_id"] == COMPUTER_ID
    assert body["provider"] == "daytona"
    assert body["provider_sandbox_id"] == "sbx-1"
    assert body["run_id"] == RUN_ID
    assert body["started_at"] == "2026-11-01T00:00:00Z"
    assert body["ended_at"] == "2026-11-01T01:00:00Z"
    assert body["total_credits"] == 165
    assert isinstance(body["total_credits"], int)
    assert body["currency"] == "CNY"
    assert body["gpu_seconds"] == 0
    assert body["cpu_credits"] == 94.3488
    assert body["memory_credits"] == 60.6528
    assert body["disk_credits"] == 9.6034
    assert body["idempotency_key"] == f"dsalpha:computer_run:{RUN_ID}"
    assert body["idempotency_key"] == idempotency_key(RUN_ID)
    assert body["unit_prices"]["markup_bps"] == MARKUP_BPS
    assert body["unit_prices"]["usd_to_credits"] == USD_TO_CREDITS


# -- org resolution ---------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_org_reads_the_flat_org_object_and_signs_with_the_service_id(console):
    console.responses = [
        FakeResponse(
            200,
            {"id": ORG_ID, "name": "Personal", "slug": "personal", "plan_code": "free"},
        )
    ]
    assert await resolve_org(USER_ID, client=console) == ORG_ID

    url, content, headers = console.posts[0]
    assert url == "https://console.test/console-api/internal/v1/orgs/resolve-user"
    assert json.loads(content) == {"user_id": USER_ID}
    assert headers["X-Roost-Service"] == "dsalpha"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Roost-Signature"]


@pytest.mark.parametrize("status", [401, 403, 404, 500])
@pytest.mark.asyncio
async def test_resolve_org_failure_is_reported_with_its_status(console, status):
    console.responses = [FakeResponse(status, text="no")]
    with pytest.raises(billing.BillingError) as caught:
        await resolve_org(USER_ID, client=console)
    assert caught.value.status_code == status


# -- one run's fate ---------------------------------------------------------


@pytest.mark.asyncio
async def test_an_open_run_is_skipped_without_a_call(console, marks):
    outcome = await _attempt(_run(ended_at=None), console)
    assert outcome.status == "skipped"
    assert console.posts == []
    assert marks[0].await_count == 0
    assert marks[1].await_count == 0


@pytest.mark.asyncio
async def test_an_already_reported_run_is_skipped(console, marks):
    outcome = await _attempt(_run(billing_reported_at=T0), console)
    assert outcome.status == "skipped"
    assert console.posts == []


@pytest.mark.asyncio
async def test_a_201_marks_the_run_reported_at_the_computed_total(console, marks):
    billed, error = marks
    console.responses = [FakeResponse(201, {"charged_credits": 63})]
    outcome = await _attempt(_run(), console)

    assert outcome.status == "reported"
    assert outcome.total_credits == 63
    billed.assert_awaited_once_with(RUN_ID, 63)
    error.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_200_replay_is_a_success(console, marks):
    billed, _ = marks
    console.responses = [FakeResponse(200, {"replayed": True})]
    outcome = await _attempt(_run(), console)
    assert outcome.status == "reported"
    billed.assert_awaited_once_with(RUN_ID, 63)


@pytest.mark.asyncio
async def test_the_total_the_console_reports_is_what_the_row_records(console, marks):
    billed, _ = marks
    console.responses = [FakeResponse(201, {"charged_credits": 60})]
    outcome = await _attempt(_run(), console)

    assert outcome.total_credits == 60
    billed.assert_awaited_once_with(RUN_ID, 60)


@pytest.mark.asyncio
async def test_a_402_leaves_the_run_queued_for_a_top_up(console, marks):
    billed, error = marks
    console.responses = [FakeResponse(402, text="insufficient credits")]
    outcome = await _attempt(_run(), console)

    assert outcome.status == "retry"
    assert outcome.total_credits == 63
    billed.assert_not_awaited()
    error.assert_awaited_once()
    assert error.await_args.kwargs["final"] is False
    assert "402" in error.await_args.args[1]


@pytest.mark.parametrize("status", [400, 409, 422])
@pytest.mark.asyncio
async def test_a_permanent_4xx_settles_the_run_with_its_error(console, marks, status):
    billed, error = marks
    console.responses = [FakeResponse(status, text="invalid sandbox usage")]
    outcome = await _attempt(_run(), console)

    assert outcome.status == "failed"
    billed.assert_not_awaited()
    error.assert_awaited_once()
    assert error.await_args.kwargs["final"] is True
    assert str(status) in error.await_args.args[1]


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
@pytest.mark.asyncio
async def test_scope_outage_and_server_answers_keep_the_run_queued(
    console, marks, status
):
    billed, error = marks
    console.responses = [FakeResponse(status, text="not yet")]
    outcome = await _attempt(_run(), console)

    assert outcome.status == "retry"
    billed.assert_not_awaited()
    assert error.await_args.kwargs["final"] is False


@pytest.mark.asyncio
async def test_a_transport_failure_keeps_the_run_queued(console, marks):
    class Broken(FakeClient):
        async def post(self, url, content=None, headers=None):
            raise TimeoutError("upstream timed out")

    billed, error = marks
    outcome = await _attempt(_run(), Broken())

    assert outcome.status == "retry"
    billed.assert_not_awaited()
    assert error.await_args.kwargs["final"] is False


@pytest.mark.asyncio
async def test_a_run_with_no_resources_is_settled_rather_than_retried(console, marks):
    _, error = marks
    outcome = await _attempt(_run(cpu=None), console)
    assert outcome.status == "failed"
    assert error.await_args.kwargs["final"] is True


@pytest.mark.asyncio
async def test_a_zero_duration_run_is_settled_rather_than_retried(console, marks):
    _, error = marks
    outcome = await _attempt(_run(ended_at=T0), console)
    assert outcome.status == "failed"
    assert error.await_args.kwargs["final"] is True


# -- a batch ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_closed_runs_resolves_each_user_once(console, marks, monkeypatch):
    billed, _ = marks
    runs = [
        _run(run_id="run-1"),
        _run(run_id="run-2"),
    ]
    monkeypatch.setattr(
        billing.runs_db, "list_runs_for_billing", AsyncMock(return_value=runs)
    )
    console.responses = [
        FakeResponse(200, {"id": ORG_ID}),
        FakeResponse(201, {}),
        FakeResponse(201, {}),
    ]

    result = await report_closed_runs(
        client=console,
        prices=PRICES,
        markup_bps=MARKUP_BPS,
        usd_to_credits=USD_TO_CREDITS,
    )

    assert result.listed == 2
    assert result.reported == 2
    assert len(console.posts) == 3  # one resolve, two reports
    assert billed.await_count == 2


@pytest.mark.asyncio
async def test_report_closed_runs_does_not_resolve_the_same_failing_user_twice(
    console, marks, monkeypatch, caplog
):
    runs = [_run(run_id="run-1"), _run(run_id="run-2")]
    monkeypatch.setattr(
        billing.runs_db, "list_runs_for_billing", AsyncMock(return_value=runs)
    )
    console.responses = [FakeResponse(403, text="scope does not allow")]

    result = await report_closed_runs(
        client=console,
        prices=PRICES,
        markup_bps=MARKUP_BPS,
        usd_to_credits=USD_TO_CREDITS,
    )

    assert result.retried == 2
    assert len(console.posts) == 1  # the failed lookup was remembered


@pytest.mark.asyncio
async def test_no_auth_service_means_no_billing(console, marks, monkeypatch):
    monkeypatch.setattr(billing, "AUTH_SERVICE_URL", "")
    result = await report_closed_runs(client=console)
    assert result.listed == 0
    assert console.posts == []


@pytest.mark.asyncio
async def test_report_once_reports_the_named_run(console, marks, monkeypatch):
    billed, _ = marks
    monkeypatch.setattr(
        billing.runs_db, "get_computer_run", AsyncMock(return_value=_run())
    )
    console.responses = [FakeResponse(200, {"id": ORG_ID}), FakeResponse(201, {})]

    outcome = await report_once(
        RUN_ID,
        client=console,
        prices=PRICES,
        markup_bps=MARKUP_BPS,
        usd_to_credits=USD_TO_CREDITS,
    )

    assert outcome.status == "reported"
    billed.assert_awaited_once_with(RUN_ID, 63)


# -- usage-only reporting ---------------------------------------------------


def test_the_body_carries_the_usage_quantities_the_console_prices():
    """The console now prices a sandbox from its settings, so the body's
    authoritative part is the usage. The legacy credit fields stay for the
    transition (and the comparison), but they are not the price."""
    charge = compute_charge(2, 4, 100, 3600, MARKUP_BPS, USD_TO_CREDITS)
    body = build_usage_body(
        _run(),
        ORG_ID,
        charge,
        prices=PRICES,
        markup_bps=MARKUP_BPS,
        usd_to_credits=USD_TO_CREDITS,
    )

    assert body["billable_seconds"] == 3600
    assert body["cpu_cores"] == 2.0
    assert body["memory_gb"] == 4.0
    assert body["disk_gb"] == 100.0
    assert body["cpu_seconds"] == 7200
    assert body["memory_mib_seconds"] == 4 * 1024 * 3600
    assert body["disk_mib_seconds"] == 100 * 1024 * 3600


def test_the_price_resolves_from_the_console_snapshot_when_not_passed():
    from src.config import billing_rates as cache

    cache.apply(
        cache.BillingRates(
            usd_to_credits=680,
            markup_bps=15000,
            source=cache.SOURCE_CONSOLE,
            markup_source=cache.SOURCE_CONSOLE,
        )
    )
    try:
        live = compute_charge(1, 1, 5, 3600)
        explicit = compute_charge(1, 1, 5, 3600, 15000, 680)
        assert live == explicit
        assert live.total_credits != compute_charge(
            1, 1, 5, 3600, MARKUP_BPS, USD_TO_CREDITS
        ).total_credits
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_a_console_charge_that_disagrees_with_the_estimate_is_reported(
    console, marks, caplog
):
    billed, _ = marks
    console.responses = [FakeResponse(201, {"charged_credits": 60})]
    with caplog.at_level("WARNING"):
        outcome = await _attempt(_run(), console)

    assert outcome.total_credits == 60
    # The console's figure is the recorded one; the local estimate is only the
    # transition's comparison.
    billed.assert_awaited_once_with(RUN_ID, 60)
    assert "price disagreement" in caplog.text
    assert "estimated 63" in caplog.text
    assert "console charged 60" in caplog.text
