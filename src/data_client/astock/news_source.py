"""A-share news, from the causal-memory hub's ``astock-data`` MCP server.

TickerTick and FMP are the English-language wire the News page was built on, so
its source filter listed only BBC/CNBC/TechCrunch and the like. The Chinese
sources the hub already carries — 数据宝, 南方财经网, 东方财富 — are reachable
through the same wire, so this maps them onto the common ``NewsArticle`` shape
and the existing provider switch (``?provider=astock``) selects it.

Two hub tools, and which one is used depends on what was asked for:

* ``global-data-get_a_global_news`` needs no arguments and returns the
  market-wide flash feed. Its rows carry only ``{title, summary, time}`` — no
  url and no outlet — so those land as a synthesized id and a stand-in source.
* ``astock-data-get_a_news`` is per-symbol, and its rows are richer:
  ``{title, content, time, source, url}``.

Both return a JSON array as the text of an MCP tool result.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# The hub proxy endpoint. Overridable so a deployment can point at its own hub,
# or at the astock service directly when it runs beside the backend.
DEFAULT_MCP_URL = "https://causal-memory.com/hub/mcp/data"

# MCP servers here speak streamable HTTP; the handshake is cheap and the news
# path is not hot, so each call opens its own session rather than holding one
# open across a long-lived process.
_TIMEOUT = httpx.Timeout(30.0, read=90.0)
_PROTOCOL = "2025-06-18"

# The hub's timestamps are Beijing wall-clock. Reading them as UTC put every
# article eight hours into the future, which the UI rendered as "8小时后" on a
# feed of things that had already happened.
_CN_TZ = timezone(timedelta(hours=8))


def _endpoint() -> str:
    return os.environ.get("ASTOCK_MCP_URL", "").strip() or DEFAULT_MCP_URL


def available() -> bool:
    """Usable when a hub token is configured — the server address has a default."""
    return bool(os.environ.get("MCPHUB_TOKEN", "").strip())


def _parse_result_text(body: str) -> str:
    """Pull the tool result text out of either SSE framing or a bare JSON body."""
    chunks: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            chunks.append(line[5:].strip())
    payload = "\n".join(chunks) if chunks else body.strip()
    try:
        doc = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    if isinstance(doc, dict) and doc.get("error"):
        logger.warning("astock news tool error: %s", doc["error"])
        return ""
    result = doc.get("result") if isinstance(doc, dict) else None
    if not isinstance(result, dict):
        return ""
    return "".join(
        c.get("text", "") for c in (result.get("content") or []) if isinstance(c, dict)
    )


async def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Run one MCP tool call and decode its JSON payload, or None."""
    token = os.environ.get("MCPHUB_TOKEN", "").strip()
    if not token:
        return None
    url = _endpoint()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            init = await client.post(
                url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _PROTOCOL,
                        "capabilities": {},
                        "clientInfo": {"name": "athena-news", "version": "1"},
                    },
                },
            )
            init.raise_for_status()
            session = init.headers.get("mcp-session-id", "")
            if session:
                headers["mcp-session-id"] = session
            await client.post(
                url,
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            resp = await client.post(
                url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            resp.raise_for_status()
            text = _parse_result_text(resp.text)
    except Exception:  # noqa: BLE001 — a news provider must never break the page
        logger.warning("astock news call failed: %s", name, exc_info=True)
        return None

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _iso(value: Any) -> str:
    """Hub timestamps are 'YYYY-MM-DD HH:MM:SS' Beijing wall-clock; the shape
    wants ISO-8601 with an offset. Parsed as +08:00 so the value is the instant
    it names, not that instant minus eight hours."""
    if not isinstance(value, str) or not value.strip():
        return ""
    raw = value.strip().replace("/", "-")
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",  # research reports carry milliseconds
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=_CN_TZ)
            return dt.isoformat()
        except ValueError:
            continue
    return value


def _article_id(url: str, title: str) -> str:
    """A stable handle for the article. The hub's rows carry no id, and the URL
    is what a cursor round-trips, so it is the id when present."""
    return url or hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]


def _normalize(raw: dict[str, Any], tickers: list[str] | None = None) -> dict[str, Any]:
    """Map one astock row → the common NewsArticle dict."""
    url = str(raw.get("url") or "")
    title = str(raw.get("title") or "")
    return {
        "id": _article_id(url, title),
        "title": title,
        "author": None,
        "description": raw.get("content") or raw.get("summary") or None,
        "published_at": _iso(raw.get("time")),
        "article_url": url,
        "image_url": None,
        "source": {
            # The market-wide flash feed names no outlet; the page's source
            # filter would otherwise show a blank row for every article.
            "name": str(raw.get("source") or "A股快讯"),
            "logo_url": None,
            "homepage_url": None,
            "favicon_url": None,
        },
        "tickers": [t.upper() for t in (tickers or [])],
        "keywords": [],
        "sentiments": None,
    }


_A_SHARE_RE = re.compile(r"^(?:sh|sz|bj)?(\d{6})$")


def _is_a_share(symbol: str) -> bool:
    """Six digits, with or without an exchange prefix. Enough to tell an A-share
    from a US ticker without needing a symbol master."""
    return bool(_A_SHARE_RE.match(symbol.strip().lower()))


def _feed(
    raw: dict[str, Any],
    *,
    source: str,
    tickers: list[str] | None = None,
    author: str | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize a row from any of the hub's feeds into the common shape."""
    url = str(raw.get("url") or raw.get("encodeUrl") or "")
    title = str(raw.get("title") or "")
    return {
        "id": _article_id(url, title),
        "title": title,
        "author": author,
        "description": raw.get("content") or raw.get("summary") or None,
        "published_at": _iso(raw.get("time") or raw.get("publishDate")),
        "article_url": url,
        "image_url": None,
        "source": {
            "name": source,
            "logo_url": None,
            "homepage_url": None,
            "favicon_url": None,
        },
        "tickers": [t.upper() for t in (tickers or [])],
        "keywords": [k for k in (keywords or []) if k],
        "sentiments": None,
    }


def _report_row(raw: dict[str, Any]) -> dict[str, Any]:
    """A research report. The publishing house is the author, and the industry
    plus rating are what a reader scans for, so both ride along as keywords."""
    org = str(raw.get("orgSName") or raw.get("orgName") or "")
    return _feed(
        raw,
        source="行业研报",
        author=org or None,
        keywords=[
            str(raw.get("industryName") or ""),
            str(raw.get("emRatingName") or ""),
            str(raw.get("stockName") or ""),
        ],
    )


def _bare_code(symbol: str) -> str:
    """The hub wants 300750, not sz300750."""
    s = symbol.strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


class AstockNewsSource:
    """Chinese A-share news via the hub's astock-data MCP server."""

    async def get_news(
        self,
        tickers: list[str] | None = None,
        limit: int = 20,
        published_after: str | None = None,
        published_before: str | None = None,
        cursor: str | None = None,
        order: str | None = None,
        sort: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        wanted = max(1, int(limit or 20))

        if tickers and not any(_is_a_share(t) for t in tickers):
            # The chain stops at the first provider that answers, so a US ticker
            # here would suppress the English feeds and return nothing. Raising
            # hands the request back to them, which is what the chain's
            # exception path is for.
            raise ValueError(f"not A-share symbols: {tickers}")

        articles: list[dict[str, Any]] = []

        if tickers:
            # Per-symbol: news, research reports, and announcements. Each is a
            # separate hub tool, merged here because the provider chain stops at
            # the first source that answers and so cannot merge for us.
            for symbol in tickers[:5]:
                code = _bare_code(symbol)
                tk = [symbol.upper()]

                payload = await _call_tool(
                    "astock-data-get_a_news", {"symbol": code, "page_size": wanted}
                )
                for item in payload if isinstance(payload, list) else []:
                    if isinstance(item, dict):
                        articles.append(_normalize(item, tk))

                payload = await _call_tool(
                    "astock-data-get_a_reports", {"symbol": code, "max_pages": 1}
                )
                for item in payload if isinstance(payload, list) else []:
                    if isinstance(item, dict):
                        row = _report_row(item)
                        row["tickers"] = tk
                        articles.append(row)

                # Currently failing upstream ("Expecting value: line 1 column 1"),
                # so this contributes nothing today and starts working the moment
                # the announcer does — no change needed here.
                payload = await _call_tool(
                    "astock-data-get_a_announcements",
                    {"symbol": code, "page_size": wanted},
                )
                for item in payload if isinstance(payload, list) else []:
                    if not isinstance(item, dict):
                        continue
                    row = _feed(item, source="A股公告", tickers=tk)
                    if row["title"]:
                        articles.append(row)
        else:
            payload = await _call_tool(
                "global-data-get_a_global_news", {"page_size": wanted}
            )
            for item in payload if isinstance(payload, list) else []:
                if isinstance(item, dict):
                    articles.append(
                        _feed(item, source=str(item.get("source") or "A股快讯"))
                    )

            # Industry research, which is market-wide and so belongs on the
            # general feed. Half the page, so the flash feed keeps room.
            payload = await _call_tool(
                "astock-data-get_a_industry_reports",
                {"industry_code": "*", "max_pages": 1},
            )
            for item in payload if isinstance(payload, list) else []:
                if isinstance(item, dict):
                    articles.append(_report_row(item))

        # Reserve room for the slower-moving feed. A research report is dated
        # midnight and flash news is minutes old, so a plain newest-first slice
        # over equally-sized fetches drops every report — the feed that returns
        # exactly `wanted` rows always wins the quota. So each block is capped
        # before interleaving.
        reports = [a for a in articles if (a.get("source") or {}).get("name") == "行业研报"]
        others = [a for a in articles if (a.get("source") or {}).get("name") != "行业研报"]
        reserve = min(len(reports), max(3, wanted // 3))

        articles = others[: wanted - reserve] + reports[:reserve]
        articles.sort(key=lambda a: a.get("published_at") or "", reverse=True)
        results = articles[:wanted]

        if not results:
            # An empty page is worse than the English feed, and a hub hiccup
            # should degrade rather than blank the page.
            raise ValueError("astock returned no articles")

        # The hub resolves by recency rather than by cursor, so paging past the
        # first page would repeat it. Report no cursor instead of lying about one.
        return {"results": results, "count": len(results), "next_cursor": None}

    async def get_news_article(
        self, article_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        """Best-effort: scan the market-wide feed for a matching id."""
        payload = await _call_tool("global-data-get_a_global_news", {"page_size": 50})
        for raw in payload or []:
            if not isinstance(raw, dict):
                continue
            if _article_id(str(raw.get("url") or ""), str(raw.get("title") or "")) == article_id:
                return _normalize(raw)
        return None

    async def close(self) -> None:
        pass  # each call owns its client
