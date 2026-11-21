---
name: a-share-dragon-tiger
description: "A-share dragon-tiger list and money flow: brokerage and institutional seats, hot-money follow-through, and individual or sector fund flows. Triggers on 龙虎榜, 席位, 游资, 主力资金, 资金流, dragon tiger list."
---

# A-Share Dragon-Tiger List

Read the 龙虎榜 as a disclosure of who traded a name and how it fits the money
flow, not as a tip to copy. A seat is a broker branch, not a person; a hot-money
seat's presence is history, not a promise.

Evidence rules: `.agents/skills/research-conventions/SKILL.md`.

## Data source

`aktools` MCP — `search_interfaces` → `describe_interface` → `get_data`.
Dates are `YYYYMMDD`; a single day is `start_date=end_date`.

| Need | Likely interface | Notes |
|---|---|---|
| 龙虎榜详情 | `stock_lhb_detail_em` | one row per stock per reason |
| 个股席位 | `stock_lhb_stock_detail_em` | `symbol`, `date`, `flag="买入"/"卖出"` |
| 机构买卖统计 | `stock_lhb_jgmmtj_em` | daily institutional net |
| 活跃营业部 | `stock_lhb_hyyyb_em` | daily active seats |
| 营业部统计 | `stock_lhb_traderstatistic_em` | period ranking |
| 个股资金流 | `stock_individual_fund_flow` | `stock`, `market` (`sh`/`sz`/`bj`) |
| 资金流排名 | `stock_individual_fund_flow_rank` | `indicator="今日"/"3日"/"5日"/"10日"` |
| 行业资金流 | `stock_sector_fund_flow_rank` | `indicator`, `sector_type` |

Search "龙虎榜", "席位", "主力资金" if a name has changed. Page with
`max_rows`/`offset`; for a full day use `save_data` and compute in code.

## Workflow

1. **Scope.** One name or a date range. For a range, first group the detail by
   stock and by 上榜原因 (reason), because one stock can appear several times.
2. **Seats.** Pull buy and sell seats for the chosen stock/date. Aggregate by
   seat type: 机构专用, 沪股通/深股通, known hot-money branches, and the rest.
   Report net buy/sell by type, not a single "游资买了" headline.
3. **Follow-through.** For a multi-day window, check whether the seats that
   bought are still on the list selling, and how the stock traded after the
   disclosure. The list is published after the close; it cannot be traded on
   that day.
4. **Money flow.** Compare the dragon-tiger net with `stock_individual_fund_flow`
   (主力/超大单/大单/中单/小单) over 1/3/5/10 days. A big board seat with
   negative main flow is a distribution question, not confirmation.
5. **Output.**

```
As of: <date> (source)
Stock and reason(s) for listing
Buy seats: type, seat, amount; sell seats: same
Net by type: institutions / northbound / hot-money / other
Flow check: 1d, 3d, 5d main net flow
Read: 3 bullets (who bought, who sold, whether flow confirms)
Caveats: seat aliases, one-day noise, disclosure lag
```

## Rules

- "机构专用" can be a quant fund, a mutual fund or a seat used by several
  clients; do not name a fund from the seat alone.
- A hot-money branch is a route, not an identity. Never present a seat as a
  person's view.
- 龙虎榜 is a lagged, selective disclosure (only names that trigger the rules).
  Absence from the list is not absence of activity.
- No copy-trading, no "跟买" instructions. If the user wants a position, route
  to `trade-pitch` or `portfolio-diagnosis`.
