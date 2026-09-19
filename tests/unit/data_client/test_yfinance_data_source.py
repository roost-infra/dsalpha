"""Unit tests for the yfinance data source — no network."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.data_client.yfinance import data_source as ds
from src.data_client.yfinance.data_source import YFinanceDataSource, _fetch_history


def _history_kwargs(interval: str = "1m", **call_kwargs) -> dict:
    """Run _fetch_history with a stubbed Ticker; return the kwargs it passed."""
    ticker = MagicMock()
    ticker.history.return_value = None  # empty result — we only care about kwargs
    with patch("src.data_client.yfinance.data_source.yf.Ticker", return_value=ticker):
        _fetch_history("0700.HK", interval, **call_kwargs)
    return ticker.history.call_args.kwargs


_TODAY = "2026-09-20"


@pytest.fixture
def frozen_today(monkeypatch):
    """Pin the provider clock so cap arithmetic is deterministic."""
    from datetime import date

    pinned = date.fromisoformat(_TODAY)
    monkeypatch.setattr(ds, "_today_et", lambda: pinned)
    return pinned


def _days_before_today(days: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(_TODAY) - timedelta(days=days)).isoformat()


def test_fetch_history_end_date_is_inclusive(frozen_today):
    """to_date is inclusive per the provider contract, but yfinance's ``end``
    is an exclusive exchange-local midnight. Without the +1-day shift, a window
    ending on the current venue date silently drops today's live session —
    non-US charts froze on the prior session (frozen 0700.HK chart bug).
    """
    # 3 天前：在 1m 的 8 天上限内，clamp 不介入，断言只盯着 end 的 +1 位移
    kwargs = _history_kwargs(start=_days_before_today(3), end="2026-07-06")
    assert kwargs["start"] == _days_before_today(3)
    assert kwargs["end"] == "2026-07-07"


def test_fetch_history_open_ended_window_has_no_end_bound(frozen_today):
    kwargs = _history_kwargs(start=_days_before_today(3), end=None)
    assert kwargs["start"] == _days_before_today(3)
    assert "end" not in kwargs


def test_fetch_history_unparseable_end_passes_through(frozen_today):
    kwargs = _history_kwargs(start=None, end="garbage")
    assert kwargs["end"] == "garbage"


@pytest.mark.asyncio
async def test_get_snapshots_returns_bare_index_symbol():
    """Indices are queried from Yahoo with a caret ("^GSPC"), but the snapshot
    must echo back the bare requested symbol ("GSPC") so the provider chain
    matches it instead of dropping it as unrequested. Regression for #287.
    """
    def fake_fetch(sym: str) -> dict:
        # Mirrors the real fetch: echoes whatever symbol it was queried with.
        return {"symbol": sym, "price": 5000.0}

    with patch(
        "src.data_client.yfinance.data_source._fetch_single_snapshot",
        side_effect=fake_fetch,
    ):
        result = await YFinanceDataSource().get_snapshots(
            ["GSPC"], asset_type="indices"
        )

    assert result == [{"symbol": "GSPC", "price": 5000.0}]


@pytest.mark.asyncio
async def test_get_snapshots_preserves_order_and_drops_failures():
    """Symbol restoration stays aligned when a fetch returns None."""
    def fake_fetch(sym: str) -> dict | None:
        return None if sym == "^IXIC" else {"symbol": sym, "price": 1.0}

    with patch(
        "src.data_client.yfinance.data_source._fetch_single_snapshot",
        side_effect=fake_fetch,
    ):
        result = await YFinanceDataSource().get_snapshots(
            ["GSPC", "IXIC", "DJI"], asset_type="indices"
        )

    assert [r["symbol"] for r in result] == ["GSPC", "DJI"]


@pytest.mark.asyncio
async def test_get_snapshots_stocks_pass_symbol_through_unchanged():
    """Stocks aren't caret-prefixed; the symbol is returned as requested."""
    def fake_fetch(sym: str) -> dict:
        return {"symbol": sym, "price": 190.0}

    with patch(
        "src.data_client.yfinance.data_source._fetch_single_snapshot",
        side_effect=fake_fetch,
    ):
        result = await YFinanceDataSource().get_snapshots(["AAPL"])

    assert result == [{"symbol": "AAPL", "price": 190.0}]


# ---------------------------------------------------------------------------
# Yahoo history caps (the "5m/15m chart shows No data available" bug)
# ---------------------------------------------------------------------------
#
# Yahoo rejects a whole request — with a 200 and an EMPTY frame, not an error —
# when the span exceeds its per-interval cap (1m: 8d, sub-hour: 60d). Downstream
# that is indistinguishable from "this symbol has no data", which is how a 15min
# A-share chart ends up blank after a couple of scroll-loads.
#
# _DEFAULT_LOOKBACK only guarded the open-ended path, so an explicit `start`
# (scroll-load prepends SCROLL_CHUNK_DAYS['15min']=30d per fetch) sailed past it.

def test_start_inside_the_cap_is_untouched(frozen_today):
    """A real 5D preset (7d) must not be moved — clamping must not cost data."""
    start = _days_before_today(7)
    kwargs = _history_kwargs(start=start, end=None, interval="15m")
    assert kwargs["start"] == start


def test_scroll_load_past_the_cap_is_clamped(frozen_today):
    """The exact production failure: 15m spanning 65 days returned 0 bars."""
    start = _days_before_today(65)
    kwargs = _history_kwargs(start=start, end=None, interval="15m")
    assert kwargs["start"] == _days_before_today(59)
    # Clamped start must be strictly inside the cap, never at/over the boundary:
    # the span is measured against "now" while `start` is a midnight date.
    assert kwargs["start"] > _days_before_today(60)


def test_clamp_only_ever_moves_the_start_forward(frozen_today):
    """Never backfill more history than the caller asked for."""
    start = _days_before_today(75)
    kwargs = _history_kwargs(start=start, end=None, interval="5m")
    assert kwargs["start"] > start


def test_each_sub_hour_interval_is_capped(frozen_today):
    for interval in ("5m", "15m", "30m"):
        kwargs = _history_kwargs(start=_days_before_today(200), end=None, interval=interval)
        assert kwargs["start"] == _days_before_today(59), interval


def test_one_minute_has_a_tighter_cap(frozen_today):
    """1m allows only 8 days, far less than sub-hour's 60."""
    kwargs = _history_kwargs(start=_days_before_today(20), end=None, interval="1m")
    assert kwargs["start"] == _days_before_today(7)


def test_one_hour_is_not_capped(frozen_today):
    """Capping 1h would silently truncate legitimate multi-year history."""
    start = _days_before_today(500)
    kwargs = _history_kwargs(start=start, end=None, interval="1h")
    assert kwargs["start"] == start


def test_unparseable_start_passes_through(frozen_today):
    """Preserves the pre-existing lenient behaviour for malformed input."""
    kwargs = _history_kwargs(start="garbage", end=None, interval="15m")
    assert kwargs["start"] == "garbage"


def test_omitted_dates_still_use_the_default_lookback(frozen_today):
    """The clamp must not disturb the open-ended path it was added beside."""
    kwargs = _history_kwargs(start=None, end=None, interval="15m")
    assert kwargs["start"] == _days_before_today(57)


def test_clamped_start_still_respects_an_explicit_end(frozen_today):
    """Clamping the start must not touch the end shift (today's live session)."""
    kwargs = _history_kwargs(start=_days_before_today(65), end="2026-09-18", interval="15m")
    assert kwargs["start"] == _days_before_today(59)
    assert kwargs["end"] == "2026-09-19"
