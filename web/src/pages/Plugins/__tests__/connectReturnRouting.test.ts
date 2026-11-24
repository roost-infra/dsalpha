/**
 * Where a connect's answer lands, now that the connectors section lives on
 * `/apps`.
 *
 * This is the one that can strand a user: a sign-in that fails has to reopen on
 * the page that hosts its form, or the retry has nowhere to go. So both sides
 * are pinned — the params a failure builds, and the page those params resolve
 * to. A bug that made `landingPlace` name the right tab but `pageHref` pick the
 * old page would pass either case alone and fail exactly here.
 */
import { describe, it, expect } from 'vitest';

import { landingPlace } from '../connectLanding';
import { pageHref } from '../utils/routes';
import type { ConnectRetry } from '../connectReturn';

/** Where a failure of this kind puts the user, as a URL. */
function landingUrl(retry: ConnectRetry, params = new URLSearchParams()): string | null {
  const place = landingPlace(retry, params);
  return place ? pageHref(place) : null;
}

const SERVER: ConnectRetry = { kind: 'server', server: { name: 'acme', transport: 'http' } };
const SERVER_EDIT: ConnectRetry = {
  kind: 'server_edit',
  name: 'acme',
  server: { name: 'acme', transport: 'http' },
};

describe('a failed connect reopens its form on the page that hosts it', () => {
  it('takes a connector form to /apps, where the connectors section lives', () => {
    expect(landingUrl(SERVER)).toBe('/apps?tab=mcp');
    expect(landingUrl(SERVER_EDIT)).toBe('/apps?tab=mcp');
  });

  it('keeps a plugin or an upload on /plugins', () => {
    expect(landingUrl({ kind: 'plugin', sourceUrl: 'https://example.com/x.git' })).toBe(
      '/plugins?tab=plugins',
    );
    expect(landingUrl({ kind: 'plugin_upload' })).toBe('/plugins?tab=plugins');
  });

  it('reopens a catalog install on Discover, on the page its section lives on', () => {
    // A connector's catalog entry is Discover on /apps; a plugin's is on
    // /plugins. The tab says which, and the page follows from it.
    expect(landingUrl({ kind: 'catalog', entry: 'polygon' }, new URLSearchParams({ tab: 'mcp' }))).toBe(
      '/apps?tab=mcp&detail=catalog%3Apolygon&view=discover',
    );
    expect(
      landingUrl({ kind: 'catalog', entry: 'ledger' }, new URLSearchParams({ tab: 'plugins' })),
    ).toBe('/plugins?tab=plugins&detail=catalog%3Aledger&view=discover');
  });

  it('defaults a catalog install with no section to the Plugins page', () => {
    const place = landingPlace({ kind: 'catalog', entry: 'ledger' }, new URLSearchParams())!;
    expect(place.get('tab')).toBe('plugins');
    expect(pageHref(place).startsWith('/plugins?')).toBe(true);
  });

  // The `catalog` branch's tab default is unreachable today — Discover is its
  // only entry point and its tab is always one of the three. This pins the one
  // route that actually runs, so the branch cannot go stale unnoticed: a
  // catalogue install begun from the connectors surface must come back to
  // `/apps`, where that surface lives.
  it('reopens a connector catalog install on /apps, not the Plugins page', () => {
    const fromConnectors = new URLSearchParams({ tab: 'mcp', q: 'polygon' });
    expect(landingUrl({ kind: 'catalog', entry: 'polygon' }, fromConnectors)).toBe(
      '/apps?tab=mcp&q=polygon&detail=catalog%3Apolygon&view=discover',
    );
  });

  it('has no form to reopen for a reconnect, a brokerage or a workspace connect', () => {
    expect(landingPlace({ kind: 'other' }, new URLSearchParams())).toBeNull();
  });

  it('drops the callback params and the view a form does not want', () => {
    // `view` and `detail` belong to the section the user was in, and a form
    // is not Discover, so both go; the tab stays, since the form is on it.
    const at = new URLSearchParams({ tab: 'mcp', view: 'discover', detail: 'catalog:x', q: 'foo' });
    const place = landingPlace(SERVER, at)!;
    expect(place.get('view')).toBeNull();
    expect(place.get('detail')).toBeNull();
    expect(pageHref(place)).toBe('/apps?tab=mcp&q=foo');
  });

  it('keeps the section the user was in when the step allows it', () => {
    expect(landingUrl({ kind: 'plugin', sourceUrl: 'https://example.com/x.git' }, new URLSearchParams({ tab: 'plugins', q: 'foo' }))).toBe(
      '/plugins?tab=plugins&q=foo',
    );
  });
});

describe('a successful connect lands on the page that owns what it connected', () => {
  it('follows a server detail to /apps and a plugin detail to /plugins', () => {
    // The success path strips the callback params off whatever page the
    // callback landed on, and reuses the same `pageHref` — so the item's page
    // is on the page that hosts its section, the same rule as the failure path.
    expect(pageHref(new URLSearchParams({ tab: 'mcp', detail: 'server:acme' }))).toBe(
      '/apps?tab=mcp&detail=server%3Aacme',
    );
    expect(pageHref(new URLSearchParams({ tab: 'plugins', detail: 'plugin:ledger' }))).toBe(
      '/plugins?tab=plugins&detail=plugin%3Aledger',
    );
  });
});
