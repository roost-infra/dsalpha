# sec-filings

SEC EDGAR for US-listed companies, wrapping
[`@cyanheads/secedgar-mcp-server`](https://github.com/cyanheads/secedgar-mcp-server)
(Apache-2.0). No API key: EDGAR is public, and the server identifies itself with
the `EDGAR_USER_AGENT` in `mcp.json`, as the SEC requires. The value points at
dsalpha's support address; an operator can override it in `agent_config.yaml`
if their deployment needs a different contact.

The server runs in the user's workspace sandbox through `npx` at the pinned
version. It covers company search, filing search back to 1993, filing sections,
XBRL financials, material events, insider Form 4s, 13F holdings, beneficial
owners and fund portfolios.

## Skills

- `sec-filing-review` — read a 10-K/10-Q/8-K/proxy: business, risk factors, MD&A, cash quality, red flags, prior-period diff.
- `sec-ownership` — Form 4 insider trades, 13F holdings, 13D/13G owners, fund portfolios, with the lag and interpretation caveats.

## Data caveats

EDGAR is the source of record, but it is not real-time: filings appear when the
company submits them, 13F is quarterly with a 45-day lag, and Form 4 is due
within two business days. An accession number plus a filing date is the
citation; a tool summary without either is not. Nothing here is investment
advice.
