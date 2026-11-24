/**
 * The two pages that host a section container on this app's primary nav, and
 * the one place that knows which section lives on which.
 *
 * `/apps` is "Connect" — what I linked — and holds the managed apps beside the
 * MCP connectors. `/plugins` is "Extensions" — what I installed — and holds the
 * plugins, skills, subagents, page plugins, brokerages and the vault.
 *
 * `/plugins` keeps its path although its display name became Extensions:
 * renaming a URL breaks every deep link, OAuth `return_to` and desktop-shell
 * route for a change the user reads in the rail, and the nav item's label
 * carries the rename on its own. The path moves only if it ever has to.
 *
 * Two pages rather than one page with a `?tab=` over both: they differ in their
 * rail, in where a connect's answer lands, and in the fallback a stray tab
 * gets, and each of those reads better as a property of the page than as a
 * branch inside a shared one.
 *
 * Everything here is derived from `?tab=` and the page paths, so a redirect, a
 * link and an OAuth return cannot disagree about where a section lives. The
 * functions are pure and live in a plain `.ts` with no imports of its own, so
 * they fold into the entry chunk and add no eagerly-loaded chunk of their own.
 */

export const PLUGINS_PATH = '/plugins';

export const APPS_PATH = '/apps';

/** The connectors surface's own URL. It lived at `/plugins?tab=mcp` before the
 *  merge, so a link into it is spelled once here rather than re-derived at each
 *  call site — and the day it moves again, this is the one line that changes. */
export const CONNECTORS_HREF = `${APPS_PATH}?tab=mcp`;

/**
 * Spellings of `?tab=` that named a section before it had its current name.
 *
 * These are URL history, not page ownership: an old bookmark keeps working
 * because the value is read as the section it meant. Resolved here so every
 * reader of a tab — the page's own section reader and the redirect below —
 * agrees on what a legacy value means.
 */
const SECTION_ALIASES: Record<string, string> = {
  /** The pre-rename connectors tab. */
  servers: 'mcp',
  /** The old Discover tab, which became the Plugins section's other view. */
  discover: 'plugins',
};

/** A `?tab=` value as the section it means, or the value itself when it means
 *  nothing special, or null when there is no value at all. */
export function normalizeSection(raw: string | null | undefined): string | null {
  if (!raw) return null;
  return SECTION_ALIASES[raw] ?? raw;
}

/**
 * The page that owns a section's list. `mcp` is the one that moved: the
 * connectors section is hosted by `/apps` now, so every link, redirect and
 * OAuth return that names it has to be read against the page, not the tab.
 *
 * An unknown section reads as the Plugins page, which leaves a link that names
 * nothing redirectable to the page that will render its default section.
 */
export function pageForSection(section: string | null | undefined): string {
  return section === 'mcp' ? APPS_PATH : PLUGINS_PATH;
}

/**
 * Where a location on the wrong page really belongs, or null when it is already
 * where it should be.
 *
 * Takes the raw query string, not a parsed map, and holds it as text: a
 * `URLSearchParams` round trip re-encodes what it did not change (`detail=
 * server:NAME` becomes `server%3ANAME`), so a redirect would rewrite a URL it
 * was only supposed to move. The one value it does write is the tab.
 *
 * Three ways a location can name the connectors section, all resolved here
 * rather than compared one by one: `?tab=mcp`, the old `?tab=servers`
 * spelling, and a bare `?detail=server:NAME`, whose kind names its section when
 * the tab is absent. `impliedSection` carries that last one in; `defaultSection`
 * is for the legacy path whose tab was never spelled at all (`/connectors`).
 */
export function relocatedHref(
  search: string,
  {
    impliedSection = null,
    defaultSection = null,
  }: { impliedSection?: string | null; defaultSection?: string | null } = {},
): string | null {
  const body = search.startsWith('?') ? search.slice(1) : search;
  const named = new URLSearchParams(body).get('tab');
  const section = normalizeSection(named) ?? normalizeSection(impliedSection) ?? defaultSection;
  const page = pageForSection(section);
  if (page === PLUGINS_PATH) return null;
  return `${page}?${withRawParam(body, 'tab', section as string)}`;
}

/** `search` with one query param set, leaving every other byte alone. */
function withRawParam(search: string, key: string, value: string): string {
  const pattern = new RegExp(`(^|&)${key}=[^&]*`);
  if (pattern.test(search)) return search.replace(pattern, `$1${key}=${value}`);
  return search ? `${search}&${key}=${value}` : `${key}=${value}`;
}

/**
 * The URL a set of page params belongs at: the page its `?tab=` names, with the
 * params as they stand.
 *
 * Built from the params rather than from a section alone because that is the
 * shape every caller has — an OAuth landing carrying the callback's params, a
 * form reopening on what the user typed — and taking them whole is what keeps
 * `?q=`, `?view=`, `?detail=` and the rest from being dropped one at a time.
 *
 * `hash` travels as it arrived: a fragment is the reader's place in a long
 * list, and a carried-through one is not ours to rebuild.
 */
export function pageHref(params: URLSearchParams, hash = ''): string {
  const search = params.toString();
  return `${pageForSection(params.get('tab'))}${search ? `?${search}` : ''}${hash}`;
}

/**
 * Whether a path is one of the container pages.
 *
 * A reader that keeps the params of the page it is on — an OAuth landing
 * building on the section the connect left from — has to know whether the page
 * it landed on is one of ours. Asking the two paths once here is what keeps a
 * reader from mistaking `/apps` for somewhere its params mean nothing, or from
 * treating an unrelated path's query as page state.
 */
export function isSectionPage(pathname: string): boolean {
  return pathname === PLUGINS_PATH || pathname === APPS_PATH;
}
