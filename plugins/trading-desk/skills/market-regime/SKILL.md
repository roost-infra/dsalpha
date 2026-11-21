---
name: market-regime
description: "Market regime check across indices, volatility, breadth and rates: risk-on or risk-off, trend and event calendar, with position-sizing implications. Triggers on market regime, risk on risk off, market environment, 市场环境, 风险偏好, 仓位."
---

# Market Regime

Decide what kind of market the next few weeks are, so the risk budget matches
it. The output is a regime with evidence and a playbook, not a forecast.

Adapted from [`tradermonty/claude-trading-skills`](https://github.com/tradermonty/claude-trading-skills)
(MIT), rewritten for dsalpha's tools.

Evidence rules: `.agents/skills/research-conventions/SKILL.md`.

## Data

| Need | Tool |
|---|---|
| Index levels and moves | `get_market_overview`, `get_quote` |
| Movers, leaders/laggards | `get_market_movers` |
| Index bars for the 200-day trend | `get_daily_prices` |
| VIX or a volatility proxy | `get_quote` |
| Macro events, central-bank dates, CPI, payrolls | `WebSearch` |
| Arithmetic (MA distance, percentiles) | `execute_code` |

Stamp every figure with its retrieval time. If a series is unavailable, say so.

## Step 1: Four lenses

1. **Trend** — for each major index (S&P 500, Nasdaq 100, Russell 2000, plus the
   user's home market), price vs its 200-day MA, the MA's slope, and the
   distance from the 52-week high. Breadth of the trend: equal-weight vs
   cap-weight, and how many sectors are above their own 200-day MA if available.
2. **Breadth** — advance/decline, new highs vs lows, percentage above the
   50-day. `get_market_movers` and `screen_stocks` can approximate a universe
   count; label it an approximation.
3. **Volatility** — VIX level and its 1-month change; a rising VIX with falling
   price is risk-off; a falling VIX with a flat price is complacency, not calm.
4. **Rates and events** — the 10-year yield and its direction, the next central
   bank meeting, CPI/payrolls, and the earnings calendar. An event inside the
   horizon caps the risk budget regardless of the trend.

## Step 2: Classify

| Regime | Evidence pattern | Risk budget |
|---|---|---|
| **Risk-on** | Indices above rising 200-day MAs, breadth expanding, VIX low/falling, no imminent event | Full planned risk; 4–6 positions at 0.5–1% risk |
| **Neutral / mixed** | Trend intact but breadth narrowing, or VIX rising, or event risk inside 2 weeks | Half risk; 2–3 positions; tighter stops |
| **Risk-off** | Price below falling 200-day MAs, breadth deteriorating, VIX rising, credit stress if visible | No new longs; manage existing; raise cash |

Mixed evidence is a regime, not a reason to average. Name the one or two
conditions that would move the call to the next bucket.

## Step 3: Implications

- Gross exposure range and the maximum single-name risk for the regime.
- Whether a breakout setup is allowed (`sepa-trend-template`), and at what
  size multiplier.
- What would flip the regime: specific levels, breadth thresholds, or events.

## Output

```
As of: <timestamp> (sources)
Trend: index, price vs 200d, 200d slope, % from 52w high
Breadth: A/D, % above 50d, sectors above 200d
Volatility: VIX, 1m change, percentile if available
Rates/events: 10y, next 3 events with dates
Regime: risk-on / neutral / risk-off
Risk budget: gross exposure, single-name risk, allowed setups
Flip conditions: 2 bullets
Data gaps
```

## Rules

- No prediction of the next index move; the regime is a risk instruction.
- A single strong day does not change the regime; require a breadth or trend
  confirmation.
- Event risk is binary: if CPI or an FOMC meeting lands inside the horizon, cap
  size even in a risk-on tape.
- Do not turn a regime call into a market-timing trade recommendation.
