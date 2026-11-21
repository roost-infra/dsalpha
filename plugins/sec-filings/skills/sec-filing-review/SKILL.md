---
name: sec-filing-review
description: "SEC filing review for US-listed companies: 10-K, 10-Q, 8-K and proxy statements plus XBRL financials, with a checklist for business, risk factors, MD&A, cash quality and red flags. Triggers on 10-K, 10-Q, 8-K, SEC filing, annual report, quarterly report, read the filing."
---

# SEC Filing Review

Read the primary document, not a summary of it. This skill turns one filing
into a review a portfolio manager can argue with: what the company says it does,
what changed, what the numbers show, and what the filing itself flags.

Evidence rules: `.agents/skills/research-conventions/SKILL.md`.

## Tools

`secedgar` MCP:

| Tool | Use |
|---|---|
| `secedgar_company_search` | ticker/name → CIK and company record |
| `secedgar_search_filings` | form type and date range → accession numbers |
| `secedgar_get_filing` | one filing's sections |
| `secedgar_get_financials` | XBRL facts across periods |
| `secedgar_get_snapshot` | latest company financial snapshot |
| `secedgar_get_material_events` | 8-K material events |
| `secedgar_fetch_frames` | one XBRL concept across companies |

Cite `form type`, `filing date` and `accession number` for every claim. If a
tool returns a summary, open the filing section behind it before quoting.

## Workflow

1. **Resolve the company.** `secedgar_company_search` by ticker; confirm the CIK
   and the fiscal year end (a retailer's FY is not the calendar year).
2. **Pick the comparison.** Latest 10-K or 10-Q plus the prior-year same period
   and the intervening 8-Ks. Note the filing date of each; a later 8-K can
   supersede part of an older 10-K.
3. **Read the filing** in this order: business, risk factors (what is new or
   reworded), MD&A (revenue drivers, margin bridge, liquidity), segments,
   critical accounting estimates, debt and commitments, legal proceedings,
   related-party transactions, subsequent events.
4. **Numbers.** Pull revenue, margins, operating cash flow, capex, debt
   maturities, share count and dilution from XBRL. Reconcile the MD&A narrative
   against the XBRL facts; when they disagree, the filing's own tables win and
   the disagreement is the finding.
5. **8-K events.** Use `secedgar_get_material_events` for the window: earnings,
   guidance, M&A, financing, delisting, auditor change, cybersecurity, officer
   changes. State the item number.
6. **Output.**

```
As of: filing date (accession)
Company / CIK / fiscal year end
Filing: form, period, accession
What changed: 3 bullets versus prior period
Numbers: revenue, margin, OCF, capex, debt, shares (period labelled)
Red flags or open questions: 2-3 bullets
Market context: price reaction since filing (optional, from get_daily_prices)
```

## Checklist for red flags

- Revenue growing faster than receivables turn or cash collection.
- Operating cash flow below net income for several periods without a stated reason.
- Capitalised costs, capitalised software or inventory rising faster than sales.
- Goodwill and intangibles large relative to equity; impairment language.
- Debt covenants close to breach; going-concern or substantial-doubt language.
- Auditor change, restatement, material weakness, late filing (NT 10-K/10-Q).
- Related-party transactions, pledges, guarantees, variable-interest entities.
- Share count rising through SBC or converts faster than the buyback retires it.

## Rules

- Quote the filing or cite the XBRL fact; no paraphrase without the source.
- A risk factor is a disclosure, not a prediction; say what would have to happen.
- Do not infer next quarter from one filing. No target price, no buy/sell call.
- If a section is missing from the extraction, say so and open the filing
  rather than inventing the content.
