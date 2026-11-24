"""Quarter comparisons using SEC submissions and US GAAP Company Facts."""

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx
from bs4 import BeautifulSoup

from src.utils.cache.redis_cache import get_cache_client

_DATA = "https://data.sec.gov"
_SEC = "https://www.sec.gov"
_HEADERS = {"User-Agent": "LangAlpha Research contact@ginlix.ai"}
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
_DOCUMENT = re.compile(r"[a-zA-Z0-9_.-]+\.html?")
_ANCHOR = re.compile(r"[a-zA-Z0-9_-]+")
_METRICS = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
}


class ResearchNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Filing:
    end: date
    filed: date
    accession: str
    form: str
    url: str

    def response(self) -> dict:
        return {"end": self.end.isoformat(), "filed": self.filed.isoformat(),
                "accession": self.accession, "form": self.form, "url": self.url}


def _filings(cik: int, submissions: dict) -> list[Filing]:
    recent = submissions["filings"]["recent"]
    fields = ("form", "reportDate", "filingDate", "accessionNumber", "primaryDocument")
    by_period: dict[date, Filing] = {}
    for form, end, filed, accession, document in zip(*(recent[field] for field in fields), strict=True):
        if form not in {"10-Q", "10-K"} or not end or not filed:
            continue
        if not _ACCESSION.fullmatch(accession) or not _DOCUMENT.fullmatch(document):
            continue
        period = date.fromisoformat(end)
        url = f"{_SEC}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}"
        candidate = Filing(period, date.fromisoformat(filed), accession, form, url)
        previous = by_period.get(period)
        if previous is None or candidate.filed > previous.filed:
            by_period[period] = candidate
    return sorted(by_period.values(), key=lambda item: item.end, reverse=True)


def _facts(rows: list[dict], filing: Filing, end: date) -> list[dict]:
    return [
        row for row in rows
        if row.get("accn") == filing.accession and row.get("end") == end.isoformat()
        and row.get("start") and type(row.get("val")) in (int, float)
    ]


def _unique(rows: list[dict]) -> dict | None:
    values = {(row["start"], row["val"]) for row in rows}
    return rows[0] if len(values) == 1 else None


def _quarter(rows: list[dict], filings: list[Filing], index: int, tag: str,
             *, comparative: Filing | None = None) -> dict | None:
    filing = filings[index]
    source = comparative or filing
    candidates = _facts(rows, source, filing.end)
    direct = [
        row for row in candidates
        if 70 <= (filing.end - date.fromisoformat(row["start"])).days <= 110
    ]

    def evidence(row: dict, origin: Filing, sign: int) -> dict:
        return {
            **origin.response(), "tag": tag, "start": row["start"], "end": row["end"],
            "value": row["val"], "sign": sign,
        }

    if direct:
        row = _unique(direct)
        if row is None:
            return None
        return {"value": row["val"], "method": "reported",
                "evidence": [evidence(row, source, 1)]}
    if comparative is not None or index + 1 >= len(filings):
        return None
    previous = filings[index + 1]
    if not 70 <= (filing.end - previous.end).days <= 110:
        return None
    prior_rows = _facts(rows, previous, previous.end)
    # Subtract a prior cumulative value only when both inputs start on the same day.
    pairs = [(row, prior) for row in candidates for prior in prior_rows if row["start"] == prior["start"]]
    values = {(row["start"], row["val"], prior["val"]) for row, prior in pairs}
    if len(values) != 1:
        return None
    current, prior = pairs[0]
    return {"value": current["val"] - prior["val"], "method": "difference",
            "evidence": [evidence(current, filing, 1), evidence(prior, previous, -1)]}


def _change(current: dict, baseline: dict | None) -> float | None:
    if baseline is None or baseline["value"] <= 0:
        return None
    return (current["value"] - baseline["value"]) / baseline["value"]


def compare_quarter(facts: dict, filings: list[Filing], index: int) -> list[dict]:
    end = filings[index].end
    preceding = index + 1 if index + 1 < len(filings) and 70 <= (end - filings[index + 1].end).days <= 110 else None
    year_earlier = min(
        (i for i in range(index + 1, len(filings)) if abs((end - filings[i].end).days - 365) <= 14),
        key=lambda i: abs((end - filings[i].end).days - 365), default=None,
    )
    metrics = []
    for key, tags in _METRICS.items():
        for tag in tags:
            rows = facts.get(tag, {}).get("units", {}).get("USD", [])
            current = _quarter(rows, filings, index, tag)
            if current is None:
                continue
            previous = _quarter(rows, filings, preceding, tag) if preceding is not None else None
            year = None
            if year_earlier is not None:
                year = (_quarter(rows, filings, year_earlier, tag, comparative=filings[index])
                        or _quarter(rows, filings, year_earlier, tag))
            metrics.append({"key": key, "current": current, "previous": previous, "year_ago": year,
                            "qoq": _change(current, previous), "yoy": _change(current, year)})
            break
    return metrics


def _filing_anchors(html: bytes) -> dict[tuple[str, str, str], str]:
    soup = BeautifulSoup(html, "html.parser")
    periods = {}
    for context in soup.find_all("xbrli:context", id=True):
        if context.find("xbrli:segment") or context.find("xbrli:scenario"):
            continue
        start, end = context.find("xbrli:startdate"), context.find("xbrli:enddate")
        if start and end:
            periods[context["id"]] = (start.get_text(strip=True), end.get_text(strip=True))
    anchors: dict[tuple[str, str, str], str] = {}
    for node in soup.find_all("ix:nonfraction", id=True):
        name = node.get("name", "")
        period = periods.get(node.get("contextref"))
        if name.startswith("us-gaap:") and period and _ANCHOR.fullmatch(node["id"]) and not node.find_parent("ix:hidden"):
            anchors.setdefault((name.split(":", 1)[1], *period), node["id"])
    return anchors


async def _json(client: httpx.AsyncClient, url: str) -> dict:
    result = await client.get(url)
    result.raise_for_status()
    return result.json()


async def load_quarter(symbol: str, period: date | None) -> dict:
    cache = get_cache_client()
    key = f"research:sec-quarter:v1:{symbol}:{period or 'latest'}"
    if cached := await cache.get(key):
        return cached
    async with httpx.AsyncClient(headers=_HEADERS, timeout=12) as client:
        tickers = await cache.get("research:sec-company-tickers:v1")
        if tickers is None:
            directory = await _json(client, f"{_SEC}/files/company_tickers.json")
            tickers = {item["ticker"]: int(item["cik_str"]) for item in directory.values()}
            await cache.set("research:sec-company-tickers:v1", tickers, ttl=86400)
        cik = tickers.get(symbol)
        if cik is None:
            raise ResearchNotFound("Ticker not found in SEC EDGAR.")
        company, companyfacts = await asyncio.gather(
            _json(client, f"{_DATA}/submissions/CIK{cik:010}.json"),
            _json(client, f"{_DATA}/api/xbrl/companyfacts/CIK{cik:010}.json"),
        )
        filings = _filings(cik, company)
        index = next((i for i, filing in enumerate(filings) if period is None or filing.end == period), None)
        if index is None:
            raise ResearchNotFound("No corresponding 10-Q or 10-K was found.")
        selected = filings[index]
        metrics = compare_quarter(companyfacts.get("facts", {}).get("us-gaap", {}), filings, index)
        if not metrics:
            raise ResearchNotFound("No comparable US GAAP quarter facts were found.")
        try:
            document = await client.get(selected.url, timeout=5)
            document.raise_for_status()
            anchors = await asyncio.to_thread(_filing_anchors, document.content)
        except httpx.HTTPError:
            anchors = {}
        for metric in metrics:
            for field in ("current", "previous", "year_ago"):
                value = metric[field]
                if value is None:
                    continue
                for source in value["evidence"]:
                    if source["accession"] != selected.accession:
                        continue
                    anchor = anchors.get((source["tag"], source["start"], source["end"]))
                    if anchor:
                        source["url"] += f"#{anchor}"
        result = {
            "symbol": symbol, "company": company["name"], "currency": "USD",
            "fetched_at": datetime.now(UTC).isoformat(), "selected": selected.response(),
            "periods": [filing.response() for filing in filings[:12]], "metrics": metrics,
        }
    await cache.set(key, result, ttl=900)
    return result
