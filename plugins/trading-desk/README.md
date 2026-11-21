# trading-desk

Two skills for discretionary equity trading, no MCP server of their own. They
use the market data the agent already has (`get_quote`, `get_daily_prices`,
`get_company_overview`, `get_market_overview`, `get_market_movers`,
`screen_stocks`, `WebSearch`) and the `execute_code` path for the arithmetic.

- `sepa-trend-template` — Minervini's 8-point trend template, stage analysis,
  VCP, pivot entry, stop and risk-based position size. Adapted from
  [`himself65/finance-skills`](https://github.com/himself65/finance-skills)
  (MIT), rewritten for dsalpha's tools.
- `market-regime` — a risk-on/risk-off dashboard across trend, breadth,
  volatility, rates and the event calendar, ending in a risk budget rather than
  a forecast. Adapted from
  [`tradermonty/claude-trading-skills`](https://github.com/tradermonty/claude-trading-skills)
  (MIT).

Both are research and risk-management aids. They do not place orders, do not
promise returns, and require the evidence conventions before a number reaches a
deliverable.
