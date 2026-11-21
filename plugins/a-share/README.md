# a-share

A-share market data for the agent, wrapping [AKTools](https://github.com/akfamily/aktools)
(MIT), AKShare's official MCP server. The server exposes four tools rather than
hundreds: `search_interfaces`, `describe_interface`, `get_data`, and `save_data`.
That keeps the prompt small while still reaching almost every AKShare interface,
including the limit-up pools, dragon-tiger lists and money-flow series that the
US data path cannot provide.

The server runs in the user's workspace sandbox, launched by `uvx` at the pinned
version in `mcp.json`. The first launch downloads AKShare and its dependencies
(about 150 MB), so a cold first call can take a few minutes; later launches use
`uvx`'s cache. The sandbox needs outbound network access for that first install
and for the data sources themselves.

## Skills

- `a-share-market-review` — the close review: indices, turnover, breadth, sectors, northbound and market flow.
- `a-share-limit-up` — limit-up and broken-board tape: pools, board ladder, follow-through.
- `a-share-dragon-tiger` — dragon-tiger list: seats, institutions, hot money, and fund flows.
- `a-share-fundamentals` — financial statements and ratios, earnings pre-announcements, research notes and announcements.

## Data caveats

AKShare is a scraper over public sources (Eastmoney, Sina, Tencent, CNINFO, ...).
Names and columns differ by source and can change without notice, so every skill
starts with `search_interfaces` rather than a hard-coded call. Eastmoney quote
interfaces rate-limit by IP; use the alternatives that `describe_interface`
lists for bulk work. Nothing here is investment advice: the skills require an
as-of stamp and a source on every figure and say "unavailable" when a series is
missing.
