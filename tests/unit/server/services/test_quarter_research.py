import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest

from src.server.services import quarter_research
from src.server.services.quarter_research import (
    Filing,
    _filing_anchors,
    compare_quarter,
)


def _filing(end: str, accession: str, form: str = "10-Q") -> Filing:
    period = date.fromisoformat(end)
    return Filing(period, period, accession, form, "https://www.sec.gov/filing.htm")


def _fact(accession: str, start: str, end: str, value: int) -> dict:
    return {"accn": accession, "start": start, "end": end, "val": value}


def test_annual_report_produces_quarter_only_with_comparable_cumulative_input():
    filings = [_filing("2025-12-31", "annual", "10-K"), _filing("2025-09-30", "q3")]
    facts = {"Revenues": {"units": {"USD": [
        _fact("annual", "2025-01-01", "2025-12-31", 150),
        _fact("q3", "2025-01-01", "2025-09-30", 95),
        _fact("q3", "2025-07-01", "2025-09-30", 35),
    ]}}}

    metric = compare_quarter(facts, filings, 0)[0]

    assert metric["current"]["value"] == 55
    assert metric["current"]["method"] == "difference"
    assert [entry["sign"] for entry in metric["current"]["evidence"]] == [1, -1]
    assert metric["previous"]["value"] == 35
    assert metric["yoy"] is None


def test_comparison_prefers_current_filing_and_rejects_conflicting_reported_values():
    filings = [_filing("2025-06-30", "current"), _filing("2024-06-30", "older")]
    rows = [
        _fact("current", "2025-04-01", "2025-06-30", 100),
        _fact("current", "2024-04-01", "2024-06-30", 80),
        _fact("older", "2024-04-01", "2024-06-30", 70),
    ]
    facts = {"Revenues": {"units": {"USD": rows}}}

    metric = compare_quarter(facts, filings, 0)[0]
    assert metric["yoy"] == 0.25
    assert metric["year_ago"]["evidence"][0]["accession"] == "current"

    rows.append(_fact("current", "2025-04-01", "2025-06-30", 110))
    assert compare_quarter(facts, filings, 0) == []


def test_filing_anchor_excludes_segment_and_hidden_facts():
    html = b"""
    <xbrli:context id="group"><xbrli:period>
      <xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate>
    </xbrli:period></xbrli:context>
    <xbrli:context id="segment"><xbrli:segment/><xbrli:period>
      <xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate>
    </xbrli:period></xbrli:context>
    <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    <xbrli:unit id="eur"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
    <ix:hidden><ix:nonFraction name="us-gaap:Revenues" id="hidden" contextRef="group" unitRef="usd">1</ix:nonFraction></ix:hidden>
    <ix:nonFraction name="us-gaap:Revenues" id="segment-total" contextRef="segment" unitRef="usd">1</ix:nonFraction>
    <ix:nonFraction name="us-gaap:Revenues" id="euro-total" contextRef="group" unitRef="eur">3</ix:nonFraction>
    <ix:nonFraction name="us-gaap:Revenues" id="total" contextRef="group" unitRef="usd" scale="3" sign="-">2.54</ix:nonFraction>
    <ix:nonFraction name="us-gaap:Revenues" id="duplicate-a" contextRef="group" unitRef="usd">4</ix:nonFraction>
    <ix:nonFraction name="us-gaap:Revenues" id="duplicate-b" contextRef="group" unitRef="usd">4</ix:nonFraction>
    """
    assert _filing_anchors(html) == {
        ("Revenues", "2025-04-01", "2025-06-30", Decimal("-2540")): "total",
    }


@pytest.fixture
def submissions():
    return {"name": "Example", "filings": {"recent": {
        "form": ["10-Q", "10-Q"],
        "reportDate": ["2025-06-30", "2025-03-31"],
        "filingDate": ["2025-08-02", "2025-05-02"],
        "accessionNumber": ["0000000123-25-000002", "0000000123-25-000001"],
        "primaryDocument": ["quarter2.htm", "quarter1.htm"],
    }}}


@pytest.fixture
def cache(monkeypatch):
    values = {"research:sec-company-tickers:v1": {"DEMO": 123}}
    cache = AsyncMock()
    cache.get.side_effect = values.get

    async def set_value(key, value, *, ttl):
        values[key] = value
        return True

    cache.set.side_effect = set_value
    monkeypatch.setattr(quarter_research, "get_cache_client", lambda: cache)
    return cache


@pytest.mark.asyncio
async def test_empty_filing_returns_other_reporting_periods(monkeypatch, cache, submissions):
    async def fetch(client, url):
        await asyncio.sleep(0)
        return submissions if "/submissions/" in url else {"facts": {}}

    fetch_json = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(quarter_research, "_json", fetch_json)
    document = AsyncMock(side_effect=AssertionError("no evidence to link"))
    monkeypatch.setattr(quarter_research.httpx.AsyncClient, "get", document)

    result, previous = await asyncio.gather(
        quarter_research.load_quarter("DEMO", None),
        quarter_research.load_quarter("DEMO", date(2025, 3, 31)),
    )

    assert result["metrics"] == []
    assert [period["end"] for period in result["periods"]] == ["2025-06-30", "2025-03-31"]
    assert previous["selected"]["end"] == "2025-03-31"
    assert previous["fetched_at"] == result["fetched_at"]
    assert fetch_json.await_count == 2
    document.assert_not_awaited()


@pytest.mark.asyncio
async def test_sec_rate_limit_reuses_stale_cache_and_backs_off(monkeypatch, cache, submissions):
    fetched_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    await cache.set(
        "research:sec-company:v1:123",
        {"company": submissions, "facts": {}, "fetched_at": fetched_at},
        ttl=3600,
    )
    request = httpx.Request("GET", "https://data.sec.gov")
    response = httpx.Response(429, request=request, headers={"Retry-After": "90"})
    fetch_json = AsyncMock(side_effect=httpx.HTTPStatusError("rate limit", request=request, response=response))
    monkeypatch.setattr(quarter_research, "_json", fetch_json)

    result = await quarter_research.load_quarter("DEMO", None)
    previous = await quarter_research.load_quarter("DEMO", date(2025, 3, 31))

    assert result["stale"] and previous["stale"]
    assert result["fetched_at"] == previous["fetched_at"] == fetched_at
    cache.set.assert_any_await("research:sec-data-backoff:v1", True, ttl=90)
    assert fetch_json.await_count == 2
