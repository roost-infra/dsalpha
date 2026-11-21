---
name: sepa-trend-template
description: "Mark Minervini's SEPA trend template and stage analysis for growth stocks: the 8-point template, VCP, pivot entry, stop and position sizing. Triggers on SEPA, Minervini, trend template, VCP, stage 2, pivot, 趋势模板, 成长股买点."
---

# SEPA Trend Template

Mark Minervini's Specific Entry Point Analysis: trade only Stage 2 growth
stocks, only at a precise pivot, only with the stop defining the size. The win
rate is roughly half; the edge is asymmetric payoff, not prediction.

Adapted from [`himself65/finance-skills`](https://github.com/himself65/finance-skills)
(MIT), rewritten for dsalpha's tools.

Evidence rules: `.agents/skills/research-conventions/SKILL.md`.

> Educational analysis only. Not investment advice. Never place an order from
> this output.

## Data

| Need | Tool |
|---|---|
| Two years of daily adjusted bars | `get_daily_prices` |
| Company facts, EPS/revenue, margins | `get_company_overview` |
| Benchmark and market context | `get_market_overview`, `get_daily_prices` on the benchmark |
| Peer or universe screen | `screen_stocks` |
| Arithmetic (MAs, 52-week range, ATR, RS) | `execute_code` |

Compute from bars; never estimate a moving average from a chart description.
If a series is missing, label the check "unavailable" and do not pass it.

## Step 1: The 8-point trend template

All eight must be true for a valid setup:

1. Price above the 150-day and 200-day moving averages.
2. The 150-day MA is above the 200-day MA.
3. The 200-day MA has been rising for at least one month (use the value one
   month ago, not the slope of a smoothed line).
4. The 50-day MA is above both the 150-day and 200-day MAs.
5. Price is above the 50-day MA.
6. Price is within 25% of its 52-week high.
7. Price is at least 30% above its 52-week low.
8. Relative strength: the 12-month return is in the top 30% of the named
   universe, or an RS rating ≥ 70 when the data source provides one.

Report each condition as pass/fail with the actual number. A near miss is a
fail; say so.

## Step 2: Stage analysis

- **Stage 1** — basing: price near a flat 200-day MA, MAs tangled, low volume.
  Do nothing.
- **Stage 2** — advancing: higher highs and lows, bullish MA stack, volume on
  up days. The only stage to buy.
- **Stage 3** — topping: wide swings at highs, failed breakouts, heavy volume
  without progress. No new positions.
- **Stage 4** — declining: below all MAs, bearish stack, rallies sold. Stay away.

If the stock is not Stage 2, stop and say so. Also count the base (1–2 safest,
3–4 reduce size, 5–6 half size at most).

## Step 3: VCP and the pivot

A volatility contraction pattern is 2–4 pullbacks, each shallower than the last,
with volume drying up into the final contraction. Identify:

- the pivot (the high of the last contraction, or the breakout level);
- the contraction depths and the volume dry-up;
- the tightness of the final week relative to ATR;
- whether the base is undercut (a deep undercut invalidates it).

## Step 4: Entry, stop, size

- **Entry**: at the pivot on expanding volume, not on a guess before it.
- **Stop**: below the pivot/base low, typically 4–8% below entry; use the
  structural level, not a round number.
- **Size**: `shares = floor((equity × risk_pct) / (entry − stop))`, with
  `risk_pct` 0.5–1% for a new position. Cap by liquidity: no more than ~10% of
  the 20-day average volume, and by the portfolio's single-name limit.
- **Market gate**: if `market-regime` is risk-off, halve the risk budget or
  pass; a Stage 2 stock in a Stage 4 market still fails.

## Output

```
Ticker / as-of
Trend template: 8 rows, each pass/fail with the number
Stage: 1/2/3/4 with evidence; base count
VCP: contractions, volume dry-up, pivot, undercut?
Entry / stop / stop % / risk per share
Position size: shares, % of equity, % of ADV, risk budget
What invalidates the setup: 2 bullets
Data gaps: missing series or stale bars
```

## Rules

- No target price and no expected return; the stop and the position size are
  the only risk numbers.
- Do not upgrade a Stage 3 or 4 chart because the fundamentals look good.
- Do not call a base "tight" without the ATR/volume arithmetic.
