---
name: a-share-market-review
description: "A-share close review: index moves, turnover, limit-up and limit-down breadth, sector rotation, northbound and market money flow, with an as-of stamp. Triggers on A股复盘, 今日盘面, market recap, close review, 涨停家数, 北向资金, 板块轮动."
---

# A-Share Close Review

Reconstruct one A-share trading day from data: what the indices did, how broad
the move was, which sectors led, and where money went. It is a review, not a
forecast, and it never turns into a buy or sell call.

Evidence labels, source tiers, staleness and the intake limits:
`.agents/skills/research-conventions/SKILL.md`. Read it before the first number
enters a note.

## Data source

Use the `aktools` MCP. It has four tools:

- `search_interfaces` — find AKShare interfaces by data type. Search with
  descriptive keywords, never a ticker.
- `describe_interface` — parameters, return columns, data source, and
  `alternatives` (the same data from another source).
- `get_data` — fetch a table, at most 1,000 rows per call; page with
  `max_rows`/`offset`, where a negative `offset` reads from the end.
- `save_data` — write the full table to a CSV in the sandbox for code.

Never invent an interface name. Search, describe, then call. Every interface
carries a source (Eastmoney/Sina/Tencent/CNINFO); record it beside the table.
Eastmoney's quote endpoints rate-limit by IP — for bulk or repeated pulls use a
source listed under `alternatives`, and on a 429 change source rather than
retrying the same call.

## Workflow

1. **Trading date.** Confirm the session date and that it traded
   (`tool_trade_date_hist_sina`, or search "交易日历"). Pass `date=YYYYMMDD`
   (or `start_date`/`end_date`) to every dated interface.
2. **Indices.** `stock_zh_index_spot_em` with `symbol="沪深重要指数"` for
   上证指数, 深证成指, 创业板指, 科创50, 沪深300, 中证500, 中证1000. Record
   close, % change and turnover. If the symbol spelling differs, search
   "指数 实时 行情" and use the alternative.
3. **Breadth.** `stock_zt_pool_em` (涨停池), `stock_zt_pool_dtgc_em` (跌停池),
   `stock_zt_pool_zbgc_em` (炸板池); `stock_market_activity_legu` for the
   up/down count and 赚钱效应 when it answers. Missing a pool is not zero —
   write "unavailable".
4. **Sectors.** `stock_board_industry_name_em` and `stock_board_concept_name_em`,
   sorted by 涨跌幅. Report the top and bottom five only; do not dump the board.
5. **Flows.** `stock_market_fund_flow` (主力净流入), `stock_sector_fund_flow_rank`
   (行业, `indicator="今日"`), and `stock_hsgt_fund_flow_summary_em` (北向). Note
   that northbound figures may be delayed or suspended.
6. **Write the review** in this shape, with the as-of stamp above the table:

```
As of: 2026-11-21 close (source: Eastmoney / Sina)
Index table: index, close, %chg, turnover
Breadth: limit-ups, limit-downs, broken boards, up/down ratio
Sectors: top 5 / bottom 5 by %chg
Flows: market main net flow, top sector inflows/outflows, northbound
Observations: 3 bullets (what was broad vs narrow, what led, what diverged)
Risks and data gaps: 2 bullets (missing series, source disagreement, event risk)
```

## Rules

- One green day is not a trend; say what would make it one.
- When two sources disagree on turnover or a percentage, show both and name
  the source; do not average silently.
- An index move is price; a breadth move is participation. Keep them separate.
- No prediction, no target, no "buy the dip". If the user asks for a trade,
  hand off to `trade-pitch` or `portfolio-diagnosis` instead of answering here.
