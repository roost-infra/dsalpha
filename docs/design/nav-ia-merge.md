# Navigation IA — Connect vs Extensions

Companion to issue #87 (M1). This note exists so the boundary stops being
re-litigated: which page owns which section, and why.

## The boundary, in one line

> **Connect = what I linked. Extensions = what I installed. Computer = where I
> run. Market = what can be installed.**

Two of those four are container pages on the primary nav, and the pair is easy
to confuse because both end in "the agent can use it".

| Page | Path | Means | Holds |
|---|---|---|---|
| **Connect** | `/apps` | what I linked | managed apps (Composio, no scope) · connectors (MCP, per-workspace scope) |
| **Extensions** | `/plugins` | what I installed | plugins · skills · subagents · page plugins · brokerages · secrets |

Computer (`/computers`) and Market (`/store`) are unchanged: they answer "where
does it run" and "what can be installed", which are neither of the above.

## Why the connectors moved to `/apps`

Before M1 the two lived apart: "managed apps" was `/apps` and "connectors" was
a tab of `/plugins`. To the user they were the same intent — *connect this
service to my bots* — reached two ways, and choosing between them required
knowing which implementation path a given service used. That is a distinction
only the codebase has.

So the connectors section moved to `/apps` and `/apps` became the single entry
for connecting something. What did **not** happen is a merge of the two data
models: managed apps have no scope (every bot reaches their tools), connectors
carry a per-workspace scope. They stay two sections with their own controls, and
each says what it is. Flattening them would either invent a scope the managed
apps do not have, or drop one the connectors do.

Likewise the section's whole surface moved with it — the Discover catalog, the
per-workspace scope control, the Add routes (server / import / hithink), the
detail pages. Half a section on each page would be a worse confusion than the
one M1 removed.

## `/plugins` keeps its URL

The nav item reads **Extensions**; the path stays `/plugins`. Renaming a URL
breaks every deep link, persisted OAuth `return_to`, e2e spec and desktop-shell
route for a change the user reads in the rail — and the label carries the rename
on its own. The path moves only if it ever has to, at which point the redirect
mechanism below already exists to carry the old one.

## One place decides, and everything else asks it

`web/src/pages/Plugins/utils/routes.ts` is the single source of truth for which
page hosts which section (`pageForSection`), and for the legacy `?tab=`
spellings (`normalizeSection`: `servers` → `mcp`, `discover` → `plugins`).

Everything that needs the answer reads it from there rather than deciding again:

- the two container pages (via `PageShell` in `pages/Plugins/components/shell/sections.ts`),
- the app shell's redirects (`components/Main/Main.tsx`),
- the Add menu, which names an intent's page and tab in one map pair,
- every link builder — `detailHref`, `useSectionNav`, the catalog's `returnTo`,
  the OAuth default — so a link and a redirect cannot disagree.

That is what makes the redirects correct by construction: they do not test
"is the tab `mcp`", they ask which page the section belongs to, and the same
question covers `?tab=mcp`, the old `?tab=servers` spelling and a bare
`?detail=server:NAME` (whose kind names its section when the tab is absent).

## Compatibility carried by M1

| Old URL | Lands on | How |
|---|---|---|
| `/plugins?tab=mcp*` | `/apps?tab=mcp*` | `LegacyMcpTabRedirect`, search + hash preserved, `replace` |
| `/plugins?tab=servers*` | `/apps?tab=mcp*` | same, tab normalised on the way |
| `/plugins?detail=server:NAME` | `/apps?tab=mcp&detail=server:NAME` | same, section implied by the detail's kind |
| `/connectors?…` | `/apps?tab=mcp…` | `LegacyConnectorsRedirect`, one hop |
| `/plugins?tab=<other>` | unchanged | renders in place, no redirect |

A stray `?tab=mcp` that reaches `/plugins` anyway (a hand-built URL, an old
bundle) falls back to the page's default section rather than rendering a blank
column — the redirect handles the links, the fallback handles the rest.

## Follow-ups this deliberately leaves out

- **Prose strings that still say "插件 / Plugins"** where they mean this page
  (`plugins.…manageInPlugins`, `pluginOff`, and similar). Renaming them all is a
  site-wide copy pass, not a navigation change; it belongs in its own PR. Strings
  that mean something else — "browser extension", "plugin author" — stay as they
  are.
- **A per-bot grant for managed apps**, so the two sections agree on scope.
  Needs backend work; out of M1.
- **Moving `/plugins` to `/extensions`**, if the URL is ever worth aligning with
  the name. The redirect mechanism above is the way to do it.
