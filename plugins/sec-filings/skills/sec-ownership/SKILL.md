---
name: sec-ownership
description: "SEC ownership and insider activity: Form 4 insider trades, 13F institutional holdings, 13D/13G beneficial owners and fund portfolios. Triggers on insider buying, 13F, 13D, institutional holdings, Form 4, 内部人交易, 机构持仓."
---

# SEC Ownership and Insider Activity

Who owns the company, who traded it, and when the disclosure actually happened.
Every number here is lagged and selective; the skill's job is to keep the lag
visible instead of turning a filing into a signal.

Evidence rules: `.agents/skills/research-conventions/SKILL.md`.

## Tools

`secedgar` MCP:

| Tool | Use |
|---|---|
| `secedgar_get_insider_transactions` | Form 4/5 buys, sells, grants, exercises |
| `secedgar_get_institutional_holdings` | 13F positions by filer |
| `secedgar_find_holders` | holders of one issuer |
| `secedgar_get_beneficial_owners` | 13D/13G owners and intent |
| `secedgar_get_fund_holdings` | a fund's portfolio from its filings |

Cite the form type, filer, filing date and period of report.

## Workflow

1. **Resolve the issuer** (`secedgar_company_search`) and decide which question
   is being asked: insider sentiment, institutional positioning, activist
   ownership, or a fund's portfolio.
2. **Insiders.** Pull Form 4s over 6–12 months. Separate open-market purchases
   and sales from grants, option exercises, tax withholding and 10b5-1 planned
   sales. Cluster buys by several insiders are more informative than one sale.
3. **Institutions.** 13F holdings are quarterly and due 45 days after quarter
   end; they show long US-listed positions only, with no shorts, no bonds, no
   non-US listings. Compare the change in shares and the position's share of
   the filer's book.
4. **Beneficial owners.** 13D (activist, intent to influence) and 13G (passive)
   are different animals; read Item 4 of a 13D before describing intent.
5. **Funds.** A fund's holdings are also lagged and can be a snapshot before a
   known exit. Date the snapshot.
6. **Output.**

```
As of: filing dates and periods (not today)
Issuer / CIK
Insider table: date, person, role, buy/sell, shares, value, 10b5-1 flag
Institutional: top holders, change in shares, % of book
Beneficial owners: 13D vs 13G, stake, stated intent
Read: 3 bullets (cluster, direction, lag caveat)
Caveats: 45-day 13F lag, Form 4 two-business-day due date, long-only 13F
```

## Rules

- Never present 13F or Form 4 data as real-time positioning.
- A planned 10b5-1 sale is not the same signal as a discretionary sale.
- 13F share counts can be split-adjusted; check the period before comparing.
- Do not name a "smart money" conclusion from one filer. Show the holding and
  let the reader judge.
- No copy-trading or front-running suggestions; no buy/sell call.
