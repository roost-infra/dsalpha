"""The pending-settlement worker: what it sends, and which answers keep a run
queued.

The case behind this worker is the leak the migration closes: a release that
could not read a spend figure used to retire the lease anyway. The worker reads
the durable usage row instead and settles exactly like the inline release, so
these tests pin the payload built from that row and the retryable/non-retryable
split that decides whether a run stays queued or leaves with its reason.
"""

from __future__ import annotations

import json

import pytest

from src.config import billing_rates as cache
from src.server.services import billing_settlement as worker


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
    def __init__(self, responses=None, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.posts: list[dict] = []

    async def post(self, url, content=None, headers=None):
        self.posts.append(json.loads(content))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0) if self.responses else FakeResponse(200, {})


RUN_ID = "22222222-2222-2222-2222-222222222222"
USAGE_ID = "33333333-3333-3333-3333-333333333333"
USER_ID = "44444444-4444-4444-4444-444444444444"


def row(**overrides) -> dict:
    token_usage = {
        "platform_cost": 0.0123,
        "per_call_costs": [
            {
                "model_name": "claude-sonnet-5-5",
                "input_tokens": 150_000,
                "output_tokens": 2_000,
                "cached_tokens": 0,
                "billing_type": "platform",
            }
        ],
        "by_model": {},
    }
    fields = {
        "run_id": RUN_ID,
        "user_id": USER_ID,
        "conversation_usage_id": USAGE_ID,
        "token_usage": token_usage,
        "is_byok": False,
        "total_credits": 9.5,
        "token_credits": 9.5,
        "infrastructure_credits": 0.0,
        "last_error": None,
    }
    fields.update(overrides)
    return fields


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    cache.clear()
    monkeypatch.setattr(worker, "AUTH_SERVICE_URL", "https://console.test/console-api")
    monkeypatch.setattr(worker.usage_limits, "service_token_missing", lambda: False)
    monkeypatch.setattr(
        worker.usage_limits, "signed_service_headers", lambda *a, **k: {}
    )
    yield
    cache.clear()


@pytest.fixture
def marks(monkeypatch):
    settled: list[tuple] = []
    errors: list[tuple] = []

    async def _settled(run_id, *, charged_credits=None, detail=None):
        settled.append((run_id, charged_credits, detail))
        return True

    async def _error(run_id, message):
        errors.append((run_id, message))

    monkeypatch.setattr(worker.settlement_db, "mark_settled", _settled)
    monkeypatch.setattr(worker.settlement_db, "mark_settle_error", _error)
    return {"settled": settled, "errors": errors}


# -- the payload ------------------------------------------------------------


def test_the_payload_is_the_inline_release_shape_from_the_usage_row():
    cache.apply(
        cache.BillingRates(
            usd_to_credits=720,
            markup_bps=13000,
            source=cache.SOURCE_CONSOLE,
            book_models=("claude-sonnet-5.5",),
        )
    )
    payload = worker.build_release_payload(row())

    assert payload["user_id"] == USER_ID
    assert payload["run_ref"] == RUN_ID
    assert payload["model_usage"] == [
        {
            "model": "claude-sonnet-5.5",
            "input": 150_000,
            "output": 2_000,
            "cache_read": 0,
            "cache_write": 0,
            "calls": 1,
        }
    ]
    assert payload["spent_usd"] == 0.0123
    # Transitional field for the legacy quota service; the console ignores it.
    assert payload["spent_credits"] == 9.5
    assert "byok" not in payload


def test_a_byok_usage_row_is_recorded_not_charged():
    payload = worker.build_release_payload(row(is_byok=True))
    assert payload["byok"] is True


def test_a_row_without_a_platform_usd_figure_sends_usage_only():
    token_usage = {
        "per_call_costs": [
            {
                "model_name": "m",
                "input_tokens": 10,
                "output_tokens": 1,
                "billing_type": "platform",
            }
        ]
    }
    payload = worker.build_release_payload(row(token_usage=token_usage))
    assert payload["model_usage"][0]["model"] == "m"
    assert "spent_usd" not in payload


# -- one run ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_two_hundred_stamps_the_console_charge(marks):
    client = FakeClient(
        [FakeResponse(200, {"released": True, "charged_credits": 9})]
    )
    outcome = await worker.settle_pending_run(row(), client=client)

    assert outcome.status == "settled"
    assert outcome.charged_credits == 9
    assert marks["settled"] == [(RUN_ID, 9, "settled")]
    assert len(client.posts) == 1


@pytest.mark.asyncio
async def test_a_replayed_release_reports_the_original_charge(marks):
    client = FakeClient(
        [
            FakeResponse(200, {"released": True, "charged_credits": 9}),
            FakeResponse(200, {"released": True, "charged_credits": 9}),
        ]
    )
    await worker.settle_pending_run(row(), client=client)
    # A second attempt (e.g. a crash between the accepted post and the local
    # stamp) is answered with the same figure and stamps the same way.
    await worker.settle_pending_run(row(), client=client)
    assert [entry[1] for entry in marks["settled"]] == [9, 9]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 403, 404, 429, 500, 503])
async def test_a_recoverable_answer_keeps_the_run_queued(marks, status):
    client = FakeClient([FakeResponse(status, text="try later")])
    outcome = await worker.settle_pending_run(row(), client=client)

    assert outcome.status == "retry"
    assert marks["settled"] == []
    assert marks["errors"] and marks["errors"][0][0] == RUN_ID


@pytest.mark.asyncio
async def test_a_network_failure_keeps_the_run_queued(marks):
    client = FakeClient(error=TimeoutError("read timeout"))
    outcome = await worker.settle_pending_run(row(), client=client)

    assert outcome.status == "retry"
    assert marks["settled"] == []
    assert "release unreachable" in marks["errors"][0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 409, 422])
async def test_an_answer_nothing_can_change_leaves_the_queue(marks, status):
    """409 is the already-released lease: retrying it forever would be a leak
    of a different kind (a queue that never drains)."""
    client = FakeClient([FakeResponse(status, text="nope")])
    outcome = await worker.settle_pending_run(row(), client=client)

    assert outcome.status == "failed"
    assert marks["settled"] and marks["settled"][0][0] == RUN_ID
    assert "release HTTP" in marks["settled"][0][2]


@pytest.mark.asyncio
async def test_a_run_with_no_spend_figure_leaves_the_queue_with_a_reason(marks):
    client = FakeClient()
    outcome = await worker.settle_pending_run(
        row(token_usage={}, total_credits=0), client=client
    )

    assert outcome.status == "failed"
    assert client.posts == []
    assert "neither model_usage nor spent_usd" in marks["settled"][0][2]


@pytest.mark.asyncio
async def test_a_run_with_no_principal_is_not_posted(marks):
    client = FakeClient()
    outcome = await worker.settle_pending_run(row(user_id=None), client=client)

    assert outcome.status == "failed"
    assert client.posts == []
    assert "no user/org principal" in marks["settled"][0][2]


@pytest.mark.asyncio
async def test_a_price_disagreement_is_reported(marks, caplog):
    client = FakeClient([FakeResponse(200, {"charged_credits": 900})])
    with caplog.at_level("WARNING"):
        await worker.settle_pending_run(row(), client=client)
    assert "off the spent_usd estimate" in caplog.text


# -- the sweep --------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_sweep_settles_each_due_row_and_counts_them(monkeypatch, marks):
    rows = [row(run_id=f"run-{i}") for i in range(3)]
    listed: list[int] = []

    async def _list(limit, *, grace_seconds):
        listed.append(grace_seconds)
        return rows

    async def _orphans(*, grace_seconds=3600):
        return 0

    monkeypatch.setattr(worker.settlement_db, "list_settle_pending", _list)
    monkeypatch.setattr(worker.settlement_db, "count_pending_without_usage", _orphans)
    client = FakeClient([FakeResponse(200, {"charged_credits": 9}) for _ in range(3)])

    result = await worker.settle_pending_runs(limit=10, client=client, grace_seconds=30)

    assert result.listed == 3
    assert result.settled == 3
    assert listed == [30]
    assert len(client.posts) == 3


@pytest.mark.asyncio
async def test_an_orphaned_pending_run_is_reported(monkeypatch, marks, caplog):
    async def _list(limit, *, grace_seconds):
        return []

    async def _orphans(*, grace_seconds=3600):
        return 2

    monkeypatch.setattr(worker.settlement_db, "list_settle_pending", _list)
    monkeypatch.setattr(worker.settlement_db, "count_pending_without_usage", _orphans)
    with caplog.at_level("ERROR"):
        await worker.settle_pending_runs(client=FakeClient())
    assert "no usage row to settle from" in caplog.text


@pytest.mark.asyncio
async def test_the_sweep_is_skipped_without_a_console_url(monkeypatch):
    monkeypatch.setattr(worker, "AUTH_SERVICE_URL", "")
    result = await worker.settle_pending_runs(client=FakeClient())
    assert result.listed == 0
