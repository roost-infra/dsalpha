import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router';
import { LegacyConnectorsRedirect, LegacyMcpTabRedirect } from '../Main';

/**
 * The two redirects are a compat contract, not cosmetics.
 *
 * `/connectors` is the pre-rename Connectors path: OAuth `return_to` values
 * parked in Redis before the rename still point at it with the
 * `?mcp_connected` / `?mcp_error` params the landing toast reads.
 *
 * `/plugins?tab=mcp` is the connectors section before it moved to `/apps` — and
 * the section can be named more than one way, which is the point of these
 * cases: `?tab=mcp`, the old `?tab=servers` spelling, and a bare
 * `?detail=server:NAME`, whose kind names its section when the tab is absent.
 * All three have to follow the section they mean, or a bookmarked link lands on
 * a `/plugins` that cannot render it.
 */

function LocationProbe() {
  const { pathname, search, hash } = useLocation();
  return <div data-testid="probe">{pathname + search + hash}</div>;
}

/** Renders the legacy `/connectors` entry and reports where it lands. */
function renderConnectors(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/connectors" element={<LegacyConnectorsRedirect />} />
        <Route path="/apps" element={<LocationProbe />} />
        <Route path="/plugins" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
  return screen.getByTestId('probe').textContent;
}

/** Renders `/plugins`, which redirects the connectors tab away and otherwise
 *  renders in place; reports which happened. */
function renderPlugins(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route
          path="/plugins"
          element={
            <LegacyMcpTabRedirect>
              <LocationProbe />
            </LegacyMcpTabRedirect>
          }
        />
        <Route path="/apps" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
  return screen.queryByTestId('probe')?.textContent;
}

describe('LegacyConnectorsRedirect', () => {
  it('sends the old connectors path to the connectors surface on /apps, keeping search and hash', () => {
    expect(renderConnectors('/connectors?mcp_connected=srv&tab=servers#frag')).toBe(
      '/apps?mcp_connected=srv&tab=mcp#frag',
    );
  });

  it('gives a bare /connectors the connectors tab, since that was the page', () => {
    expect(renderConnectors('/connectors')).toBe('/apps?tab=mcp');
  });

  // The fallback used to rebuild an empty query, so a `/connectors` link that
  // names a section `/plugins` still hosts lost the section, the detail and the
  // search — `/connectors?tab=skills&q=earnings&detail=skill:ledger` arrived as
  // a bare `/plugins`. It is a real shape: `/connectors` is still the value in
  // in-flight OAuth `return_to`s, and `?tab=skills` is a plausible bookmark.
  it('keeps the whole search when the alias lands on a section /plugins hosts', () => {
    expect(renderConnectors('/connectors?tab=skills&q=earnings&detail=skill:ledger#frag')).toBe(
      '/plugins?tab=skills&q=earnings&detail=skill:ledger#frag',
    );
  });

  // Why the fallback appends `search` as text rather than rebuilding it from
  // params: a round trip through `URLSearchParams` percent-encodes the colon.
  it('does not re-encode the search it carries over', () => {
    expect(renderConnectors('/connectors?tab=skills&detail=skill:ledger&q=a%20b')).toBe(
      '/plugins?tab=skills&detail=skill:ledger&q=a%20b',
    );
  });
});

describe('LegacyMcpTabRedirect', () => {
  it('redirects ?tab=mcp to /apps, preserving the rest of the query', () => {
    expect(renderPlugins('/plugins?tab=mcp&add=server&q=foo&detail=server:srv&dws=ws-1')).toBe(
      '/apps?tab=mcp&add=server&q=foo&detail=server:srv&dws=ws-1',
    );
  });

  it('redirects the old ?tab=servers spelling the same way, normalising the tab', () => {
    expect(renderPlugins('/plugins?tab=servers&q=foo')).toBe('/apps?tab=mcp&q=foo');
  });

  it('redirects a bare ?detail=server:NAME, whose kind names the connectors section', () => {
    // The tab is appended rather than moved to the front: the redirect holds the
// query as text so it does not re-encode `server:acme` on the way past.
    expect(renderPlugins('/plugins?detail=server:acme')).toBe('/apps?detail=server:acme&tab=mcp');
  });

  it('leaves a section this page still hosts alone', () => {
    expect(renderPlugins('/plugins?tab=skills&q=earnings')).toBe('/plugins?tab=skills&q=earnings');
  });

  it('lets a bare /plugins render the page itself', () => {
    expect(renderPlugins('/plugins')).toBe('/plugins');
  });
});
