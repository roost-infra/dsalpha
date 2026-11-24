/**
 * Where a section's URL points after the connectors section moved from
 * `/plugins` to `/apps`.
 *
 * One module (`utils/routes.ts`) answers this for every reader — the page's own
 * section resolver, the app shell's redirect, and the Add menu — so these cases
 * pin the answer itself rather than one call site's use of it.
 */
import { describe, it, expect } from 'vitest';

import {
  ADD_INTENT_PAGE,
  ADD_INTENT_TAB,
  ADD_PARAM,
  addIntentHref,
  parseAddIntent,
  type AddIntent,
} from '../utils/addParam';
import {
  APPS_PATH,
  CONNECTORS_HREF,
  PLUGINS_PATH,
  isSectionPage,
  normalizeSection,
  pageForSection,
  pageHref,
  relocatedHref,
} from '../utils/routes';

const INTENTS: AddIntent[] = [
  'plugin',
  'server',
  'import',
  'hithink',
  'skill',
  'subagent',
  'subagent-chat',
];

describe('which page hosts a section', () => {
  it('sends the connectors section to /apps and everything else to /plugins', () => {
    expect(pageForSection('mcp')).toBe(APPS_PATH);
    expect(pageForSection('apps')).toBe(PLUGINS_PATH);
    for (const section of ['plugins', 'skills', 'subagents', 'pages', 'brokerages', 'secrets']) {
      expect(pageForSection(section)).toBe(PLUGINS_PATH);
    }
  });

  it('reads the old spellings as the sections they meant', () => {
    expect(normalizeSection('servers')).toBe('mcp');
    expect(normalizeSection('discover')).toBe('plugins');
    expect(normalizeSection('skills')).toBe('skills');
    expect(normalizeSection(null)).toBeNull();
    expect(pageForSection(normalizeSection('servers'))).toBe(APPS_PATH);
  });

  it('recognises only the two container pages', () => {
    expect(isSectionPage('/apps')).toBe(true);
    expect(isSectionPage('/plugins')).toBe(true);
    expect(isSectionPage('/dashboard')).toBe(false);
    expect(isSectionPage('/appst')).toBe(false);
  });
});

describe('building a section URL from its params', () => {
  it('follows the tab onto the page that hosts it', () => {
    expect(pageHref(new URLSearchParams({ tab: 'mcp', add: 'server' }))).toBe(
      '/apps?tab=mcp&add=server',
    );
    expect(pageHref(new URLSearchParams({ tab: 'skills', q: 'earnings' }))).toBe(
      '/plugins?tab=skills&q=earnings',
    );
  });

  it('keeps a fragment as it arrived', () => {
    expect(pageHref(new URLSearchParams({ tab: 'mcp' }), '#item-3')).toBe('/apps?tab=mcp#item-3');
  });

  it('spells the connectors surface once', () => {
    expect(CONNECTORS_HREF).toBe(pageHref(new URLSearchParams({ tab: 'mcp' })));
  });
});

describe('relocating a location that names a section another page hosts', () => {
  it('moves ?tab=mcp to /apps, leaving the other params byte for byte', () => {
    // `server:NAME` must not become `server%3ANAME`: the redirect moves a URL,
    // it does not rewrite the parts it was not asked to change.
    expect(relocatedHref('?tab=mcp&detail=server:srv&dws=ws-1&q=foo')).toBe(
      '/apps?tab=mcp&detail=server:srv&dws=ws-1&q=foo',
    );
  });

  it('moves the old ?tab=servers spelling and normalises the tab it writes', () => {
    expect(relocatedHref('?tab=servers&q=foo')).toBe('/apps?tab=mcp&q=foo');
  });

  it('moves a bare ?detail=server:NAME, whose kind names the connectors section', () => {
    expect(relocatedHref('?detail=server:srv', { impliedSection: 'mcp' })).toBe(
      '/apps?detail=server:srv&tab=mcp',
    );
  });

  it('takes the legacy path with no tab at all, when told which section it meant', () => {
    expect(relocatedHref('?mcp_connected=srv', { defaultSection: 'mcp' })).toBe(
      '/apps?mcp_connected=srv&tab=mcp',
    );
    expect(relocatedHref('', { defaultSection: 'mcp' })).toBe('/apps?tab=mcp');
  });

  it('leaves a section this page hosts where it is', () => {
    expect(relocatedHref('?tab=skills&q=earnings')).toBeNull();
    expect(relocatedHref('?tab=brokerages')).toBeNull();
    // No tab, no detail, no default: nothing here says a section at all.
    expect(relocatedHref('?q=earnings')).toBeNull();
    expect(relocatedHref('?detail=skill:ledger')).toBeNull();
  });
});

describe('the Add menu intent, split into a page and a tab', () => {
  it('sends the connector intents to the page that hosts their drawer', () => {
    for (const intent of ['server', 'import', 'hithink'] as const) {
      expect(ADD_INTENT_PAGE[intent]).toBe(APPS_PATH);
      expect(ADD_INTENT_TAB[intent]).toBe('mcp');
    }
    for (const intent of ['plugin', 'skill', 'subagent', 'subagent-chat'] as const) {
      expect(ADD_INTENT_PAGE[intent]).toBe(PLUGINS_PATH);
    }
  });

  it('keeps the two maps in step with the page each intent actually lands on', () => {
    // The invariant the split exists for: an intent's page is the page that
    // hosts its tab. A tab written into ADD_INTENT_TAB that the page in
    // ADD_INTENT_PAGE does not render would open a drawer on a blank column.
    for (const intent of INTENTS) {
      expect(pageForSection(ADD_INTENT_TAB[intent])).toBe(ADD_INTENT_PAGE[intent]);
      expect(addIntentHref(intent)).toBe(
        `${ADD_INTENT_PAGE[intent]}?tab=${ADD_INTENT_TAB[intent]}&${ADD_PARAM}=${intent}`,
      );
    }
  });

  it('parses back only the intents it wrote', () => {
    const href = addIntentHref('server');
    const params = new URLSearchParams(href.split('?')[1]);
    expect(parseAddIntent(params)).toBe('server');
    expect(parseAddIntent(new URLSearchParams({ [ADD_PARAM]: 'nonsense' }))).toBeNull();
    expect(parseAddIntent(new URLSearchParams())).toBeNull();
  });
});
