"""Quarter comparisons using SEC submissions and US GAAP Company Facts."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
from bs4 import BeautifulSoup

from src.utils.cache.redis_cache import RedisCacheClient, get_cache_client

_DATA = "https://data.sec.gov"
_SEC = "https://www.sec.gov"
_HEADERS = {"User-Agent": "LangAlpha Research contact@ginlix.ai"}
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
_DOCUMENT = re.compile(r"[a-zA-Z0-9_.-]+\.html?")
_ANCHOR = re.compile(r"[a-zA-Z0-9_-]+")
_COMPANY_FRESH_SECONDS = 900
_COMPANY_STALE_SECONDS = 86400
_SEC_RETRYABLE = {429, 500, 502, 503, 504}
_DATA_BACKOFF_KEY = "research:sec-data-backoff:v1"
_TICKERS_KEY = "research:sec-company-tickers:v1"
_inflight: dict[str, asyncio.Task] = {}
_DOT_DECIMAL = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?")
_COMMA_DECIMAL = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]+)?")
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
        if form not in {"10-Q", "10-K", "10-Q/A", "10-K/A"} or not end or not filed:
            continue
        if not _ACCESSION.fullmatch(accession) or not _DOCUMENT.fullmatch(document):
            continue
        period = date.fromisoformat(end)
        url = f"{_SEC}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}"
        candidate = Filing(period, date.fromisoformat(filed), accession, form, url)
        previous = by_period.get(period)
        if previous is None or (candidate.filed, candidate.accession) > (previous.filed, previous.accession):
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
    prior_rows = _facts(rows, filing, previous.end)
    prior_source = filing
    if not prior_rows:
        # An amendment does not prove that an older cumulative input shares its basis.
        if filing.form.endswith('/A') or previous.form.endswith('/A'):
            return None
        prior_rows = _facts(rows, previous, previous.end)
        prior_source = previous
    # Subtract a prior cumulative value only when both inputs start on the same day.
    pairs = [(row, prior) for row in candidates for prior in prior_rows if row["start"] == prior["start"]]
    values = {(row["start"], row["val"], prior["val"]) for row, prior in pairs}
    if len(values) != 1:
        return None
    current, prior = pairs[0]
    return {"value": current["val"] - prior["val"], "method": "difference",
            "evidence": [evidence(current, filing, 1), evidence(prior, prior_source, -1)]}


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
            uncertainty = []
            if year_earlier is not None:
                year = _quarter(rows, filings, year_earlier, tag, comparative=filings[index])
                if year is None:
                    # Presence is not absence: an unusable restated comparison must
                    # never revive a quarter computed from superseded cumulative facts.
                    if _facts(rows, filings[index], filings[year_earlier].end):
                        uncertainty.append("comparative_basis_unavailable")
                    elif filings[index].form.endswith('/A'):
                        uncertainty.append("amendment_unverified")
                    else:
                        year = _quarter(rows, filings, year_earlier, tag)
            metrics.append({"key": key, "current": current, "previous": previous, "year_ago": year,
                            "uncertainty": uncertainty,
                            "qoq": _change(current, previous), "yoy": _change(current, year)})
            break
    return metrics


def _filing_number(text: str, transform: str, scale: str, sign: str) -> Decimal | None:
    transform = transform.split(":")[-1].lower()
    if not re.fullmatch(r"[+-]?\d{1,2}", scale) or abs(int(scale)) > 24 or sign not in {"", "-"}:
        return None
    if transform in {"", "num-dot-decimal", "numdotdecimal"} and _DOT_DECIMAL.fullmatch(text):
        digits = text.replace(",", "")
    elif transform in {"num-comma-decimal", "numcommadecimal"} and _COMMA_DECIMAL.fullmatch(text):
        digits = text.replace(".", "").replace(",", ".")
    elif transform in {"zero-dash", "zerodash", "fixed-zero"} and text in {"-", "–", "—", "0"}:
        digits = "0"
    else:
        return None
    return Decimal(f"{sign}{digits}e{scale}")


def _filing_anchors(html: bytes) -> dict[tuple[str, str, str, Decimal], str]:
    soup = BeautifulSoup(html, "html.parser")
    periods = {}
    for context in soup.find_all("xbrli:context", id=True):
        if context.find("xbrli:segment") or context.find("xbrli:scenario"):
            continue
        start, end = context.find("xbrli:startdate"), context.find("xbrli:enddate")
        if start and end:
            periods[context["id"]] = (start.get_text(strip=True), end.get_text(strip=True))
    usd_units = set()
    for unit in soup.find_all("xbrli:unit", id=True):
        measures = unit.find_all("xbrli:measure", recursive=False)
        if len(measures) == 1 and measures[0].get_text(strip=True) == "iso4217:USD":
            usd_units.add(unit["id"])
    candidates: dict[tuple[str, str, str, Decimal], list[str]] = {}
    for node in soup.find_all("ix:nonfraction", id=True):
        name = node.get("name", "")
        period = periods.get(node.get("contextref"))
        if not (
            name.startswith("us-gaap:") and period and node.get("unitref") in usd_units
            and _ANCHOR.fullmatch(node["id"]) and not node.find_parent("ix:hidden")
        ):
            continue
        number = _filing_number(
            node.get_text(strip=True), node.get("format", ""), node.get("scale", "0"), node.get("sign", ""),
        )
        if number is not None:
            candidates.setdefault((name.split(":", 1)[1], *period, number), []).append(node["id"])
    return {key: ids[0] for key, ids in candidates.items() if len(ids) == 1}


async def _json(client: httpx.AsyncClient, url: str) -> dict:
    result = await client.get(url)
    result.raise_for_status()
    return result.json()


async def _single_flight[T](key: str, fetch: Callable[[], Awaitable[T]]) -> T:
    task = _inflight.get(key)
    if task is None:
        async def run() -> T:
            return await fetch()

        def finish(done: asyncio.Task) -> None:
            _inflight.pop(key, None)
            if not done.cancelled():
                done.exception()

        task = asyncio.create_task(run())
        _inflight[key] = task
        task.add_done_callback(finish)
    return await asyncio.shield(task)


async def _load_tickers(cache: RedisCacheClient) -> dict[str, int]:
    cached = await cache.get(_TICKERS_KEY)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(headers=_HEADERS, timeout=12) as client:
        directory = await _json(client, f"{_SEC}/files/company_tickers.json")
    tickers = {item["ticker"]: int(item["cik_str"]) for item in directory.values()}
    await cache.set(_TICKERS_KEY, tickers, ttl=86400)
    return tickers


async def _fetch_company(cik: int, cache: RedisCacheClient) -> tuple[dict, bool]:
    key = f"research:sec-company:v1:{cik}"
    cached = await cache.get(key)
    if cached:
        age = (datetime.now(UTC) - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
        if age < _COMPANY_FRESH_SECONDS:
            return cached, False
    if await cache.get(_DATA_BACKOFF_KEY):
        if cached:
            return cached, True
        raise httpx.TransportError("SEC data is temporarily rate limited")

    async with httpx.AsyncClient(headers=_HEADERS, timeout=12) as client:
        try:
            company, facts = await asyncio.gather(
                _json(client, f"{_DATA}/submissions/CIK{cik:010}.json"),
                _json(client, f"{_DATA}/api/xbrl/companyfacts/CIK{cik:010}.json"),
                return_exceptions=True,
            )
            for response in (company, facts):
                if isinstance(response, BaseException):
                    raise response
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status not in _SEC_RETRYABLE:
                raise
            if status in {429, 503}:
                retry_after = error.response.headers.get("Retry-After", "")
                wait = 60
                if re.fullmatch(r"[0-9]{1,7}", retry_after):
                    wait = min(600, max(1, int(retry_after)))
                await cache.set(_DATA_BACKOFF_KEY, True, ttl=wait)
            if cached:
                return cached, True
            raise
        except httpx.TransportError:
            if cached:
                return cached, True
            raise
    result = {
        "company": company,
        "facts": facts.get("facts", {}).get("us-gaap", {}),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    await cache.set(key, result, ttl=_COMPANY_STALE_SECONDS)
    return result, False


async def _load_anchors(
    filing: Filing, cache: RedisCacheClient, *, allow_fetch: bool
) -> dict:
    key = f"research:sec-anchors:v1:{filing.accession}"
    cached = await cache.get(key)
    if cached is not None:
        return {(tag, start, end, Decimal(value)): anchor for tag, start, end, value, anchor in cached}
    if not allow_fetch:
        return {}
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=5) as client:
            document = await client.get(filing.url)
            document.raise_for_status()
        anchors = await asyncio.to_thread(_filing_anchors, document.content)
    except httpx.HTTPError:
        return {}
    await cache.set(
        key,
        [[tag, start, end, str(value), anchor] for (tag, start, end, value), anchor in anchors.items()],
        ttl=_COMPANY_STALE_SECONDS,
    )
    return anchors


async def load_quarter(symbol: str, period: date | None) -> dict:
    cache = get_cache_client()
    key = f"research:sec-quarter:v4:{symbol}:{period or 'latest'}"
    if cached := await cache.get(key):
        return cached
    tickers = await _single_flight("tickers", lambda: _load_tickers(cache))
    cik = tickers.get(symbol)
    if cik is None:
        raise ResearchNotFound("Ticker not found in SEC EDGAR.")
    data, stale = await _single_flight(f"company:{cik}", lambda: _fetch_company(cik, cache))
    company = data["company"]
    filings = _filings(cik, company)
    index = next((i for i, filing in enumerate(filings) if period is None or filing.end == period), None)
    if index is None:
        raise ResearchNotFound("No corresponding 10-Q or 10-K was found.")
    selected = filings[index]
    metrics = compare_quarter(data["facts"], filings, index)
    anchors = {}
    if metrics:
        anchors = await _single_flight(
            f"anchors:{selected.accession}:{stale}",
            lambda: _load_anchors(selected, cache, allow_fetch=not stale),
        )
    for metric in metrics:
        for field in ("current", "previous", "year_ago"):
            value = metric[field]
            if value is None:
                continue
            for source in value["evidence"]:
                if source["accession"] != selected.accession:
                    continue
                matching_fact = (source["tag"], source["start"], source["end"], Decimal(str(source["value"])))
                anchor = anchors.get(matching_fact)
                if anchor:
                    source["url"] += f"#{anchor}"
    result = {
        "symbol": symbol, "company": company["name"], "currency": "USD",
        "fetched_at": data["fetched_at"], "stale": stale, "selected": selected.response(),
        "periods": [filing.response() for filing in filings[:12]], "metrics": metrics,
        # Only the filing this page reads: an older period's amendment says
        # nothing about the numbers shown, and flags of its own ride the metric.
        "uncertainty": ["amendment_unverified"] if selected.form.endswith('/A') else [],
    }
    age = (datetime.now(UTC) - datetime.fromisoformat(data["fetched_at"])).total_seconds()
    remaining_fresh = int(_COMPANY_FRESH_SECONDS - age)
    if not stale and remaining_fresh > 0:
        await cache.set(key, result, ttl=remaining_fresh)
    return result
