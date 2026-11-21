---
name: a-share-fundamentals
description: "A-share fundamentals: financial statements and ratios, earnings pre-announcements, research notes, announcements and valuation snapshots. Triggers on A股财报, 业绩预告, 研报, 公告, 估值, financial statements, earnings forecast."
---

# A-Share Fundamentals

Read a China-listed company from its filings and data: statements, ratios,
pre-announcements, announcements, sell-side notes and the valuation snapshot.
The output separates what the company reported from what analysts expect and
from what the market pays for it.

Evidence rules: `.agents/skills/research-conventions/SKILL.md`.

## Data source

`aktools` MCP — `search_interfaces` → `describe_interface` → `get_data`.
Financial interfaces take a six-digit `symbol` (for example `600519`); dates are
`YYYYMMDD` or report periods such as `20240930`.

| Need | Likely interface | Notes |
|---|---|---|
| 财务摘要 | `stock_financial_abstract` | multi-period key lines |
| 财务指标 | `stock_financial_analysis_indicator` | ROE, margins, turnover, debt |
| 业绩报表 | `stock_yjbb_em` | `date=20240930` |
| 业绩预告 | `stock_yjyg_em` | `date=20240930`, type and range |
| 盈利预测 | `stock_profit_forecast_em` | consensus by year |
| 研究报告 | `stock_research_report_em` | ratings and target prices are sell-side views |
| 公告 | `stock_notice_report` | title/date; fetch the full text for the actual terms |
| 实时行情 | `stock_zh_a_spot_em` | price, PE/PB snapshot where present |

Search "财务 摘要", "业绩 预告", "研报", "公告" if a name has moved. Use
`save_data` for multi-year tables and compute the ratios in code.

## Workflow

1. **Reporting period.** Identify the latest filed period and the announcement
   date. A number is only "latest" relative to that date.
2. **Three statements.** Revenue, gross/operating net margin, net profit,
   operating cash flow, capex, debt, goodwill, receivables and inventory. For
   banks, insurers and brokers, skip industrial ratios and use the sector's own
   metrics.
3. **Quality checks.** Operating cash flow vs net profit over 3 years; receivables
   and inventory growth vs revenue; goodwill vs equity; related-party and
   guarantee disclosures; audit opinion. Flag what does not reconcile.
4. **Pre-announcements.** `stock_yjyg_em` gives a range, not a point. Check
   whether the range is 预增/预减/扭亏/首亏 and what the company attributes it to;
   the attribution is a claim to test, not a result.
5. **Sell-side and announcements.** Research notes are opinions with a date and
   an analyst; report the consensus and dispersion, never as fact. Read the
   announcement itself for dividends, buybacks, placements, pledges, litigation
   or control changes.
6. **Valuation snapshot.** PE/PB/PS and market cap with the as-of timestamp.
   Compare with the company's own history and peers only when the peer set is
   named; a single multiple is not "cheap" or "expensive".
7. **Output.**

```
As of: <announcement date / price timestamp> (source)
Period and statement: revenue, net profit, OCF, margins
Quality: OCF/NP, working capital, goodwill, audit
Guidance: range and company attribution
Consensus: ratings, target dispersion, revisions
Valuation: multiple, history, named peer set
Read: 3 bullets (what changed, what is priced, what to verify)
Red flags and data gaps
```

## Rules

- Never mix 报告期 and 公告日; label both.
- Do not annualise a single quarter without saying so.
- A target price is a sell-side opinion; it is not your valuation.
- No buy/sell call. If the user asks whether to own it, route to
  `company-valuation`, `earnings-analysis` or `trade-pitch`.
