from datetime import date

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
    <ix:hidden><ix:nonFraction name="us-gaap:Revenues" id="hidden" contextRef="group">1</ix:nonFraction></ix:hidden>
    <ix:nonFraction name="us-gaap:Revenues" id="segment-total" contextRef="segment">1</ix:nonFraction>
    <ix:nonFraction name="us-gaap:Revenues" id="total" contextRef="group">2</ix:nonFraction>
    """
    assert _filing_anchors(html) == {("Revenues", "2025-04-01", "2025-06-30"): "total"}
