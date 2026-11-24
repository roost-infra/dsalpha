/**
 * The `/plugins` route as the app shell actually mounts it.
 *
 * This is the assertion the pure-function suites cannot make. `relocatedHref`
 * can return exactly the right value and the page still render nothing: the
 * failure mode is *who gets mounted*, not what a function returns. React
 * Router ranks a static `/plugins` above `/plugins/*`, and a `?tab=` lives in
 * the query string, which does not participate in matching — so `pathname` is
 * `/plugins` for every tab. Split the page and the redirect across two routes
 * and the redirect wins for all of them, answering a link it does not own with
 * a blank column.
 *
 * So: one route, the redirect rendering the page when the link is not its to
 * move, and the page's own content asserted as the terminal state. `tab=mcp`
 * is the one that leaves; every tab the page hosts must stay.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import React from 'react';
import { Routes, Route, useLocation } from 'react-router';
import { renderWithProviders } from '@/test/utils';
import { queryKeys } from '@/lib/queryKeys';
import { getMarketplace, type MarketplaceResponse } from '@/pages/ChatAgent/utils/api/marketplace';
import { LegacyMcpTabRedirect } from '@/components/Main/Main';
import Plugins from '../Plugins';

vi.mock('@/pages/ChatAgent/utils/api/marketplace', () => ({ getMarketplace: vi.fn() }));

// The frame and the mount are under test; a section's own list is not.
vi.mock('../components/shell/useShellData', () => ({ useShellData: () => ({}) }));
vi.mock('../components/shell/SectionRail', () => ({ SectionRail: () => null }));
vi.mock('../components/shell/YoursSummary', () => ({ YoursSummary: () => null }));
vi.mock('../components/WorkspacesLoadNote', () => ({ WorkspacesLoadNote: () => null }));
vi.mock('../components/BuiltinPagePlugins', () => ({ BuiltinPagePlugins: () => <p>your page plugins</p> }));
vi.mock('../components/PluginsList', () => ({ PluginsList: () => <p>your plugins</p> }));
vi.mock('../components/McpServers', () => ({ McpServers: () => <p>your connectors</p> }));
vi.mock('../components/SkillsList', () => ({ SkillsList: () => <p>your skills</p> }));
vi.mock('../components/subagents/SubagentsList', () => ({ SubagentsList: () => <p>your subagents</p> }));
vi.mock('../components/Brokerages', () => ({ Brokerages: () => <p>your brokerages</p> }));
vi.mock('../components/PluginSecrets', () => ({ PluginSecrets: () => <p>your secrets</p> }));
vi.mock('../components/Discover', () => ({ Discover: () => <p>the catalog</p> }));

// The Add menu inline: the Radix one opens on pointer events jsdom does not drive.
vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div role="menu">{children}</div>,
  DropdownMenuSeparator: () => null,
  DropdownMenuItem: ({ children, onSelect }: { children: React.ReactNode; onSelect?: () => void }) => (
    <button role="menuitem" onClick={() => onSelect?.()}>
      {children}
    </button>
  ),
}));

function listing(configured: boolean): MarketplaceResponse {
  return {
    configured,
    name: null,
    description: null,
    url: null,
    vocabulary: { assets: [], regions: [], data: [] },
    entries: [],
  };
}

function Address() {
  return <output data-testid="address">{useLocation().pathname + useLocation().search}</output>;
}

/** The route table Main.tsx mounts: one `/plugins`, the redirect rendering the
 *  page when the link is not a moved section's. */
function renderPluginsRoute(entry: string) {
  const view = renderWithProviders(
    <>
      <Routes>
        <Route
          path="/plugins"
          element={
            <LegacyMcpTabRedirect>
              <Plugins />
            </LegacyMcpTabRedirect>
          }
        />
        <Route path="/apps" element={<Address />} />
      </Routes>
    </>,
    { route: entry },
  );
  const answered = () =>
    waitFor(() =>
      expect(view.queryClient.getQueryState(queryKeys.plugins.marketplace())?.status).not.toBe('pending'),
    );
  return { ...view, answered };
}

beforeEach(() => {
  vi.mocked(getMarketplace).mockReset();
  vi.mocked(getMarketplace).mockResolvedValue(listing(false));
});

describe('the /plugins route as mounted', () => {
  // The P0 this pins: every one of these rendered a blank column when the
  // redirect had its own route and returned null for a link it did not own.
  it.each([
    ['/plugins', 'your plugins'],
    ['/plugins?tab=plugins', 'your plugins'],
    ['/plugins?tab=pages', 'your page plugins'],
    ['/plugins?tab=skills', 'your skills'],
    ['/plugins?tab=subagents', 'your subagents'],
    ['/plugins?tab=brokerages', 'your brokerages'],
    ['/plugins?tab=secrets', 'your secrets'],
  ])('renders the page for %s', async (entry, expected) => {
    const { answered, container } = renderPluginsRoute(entry);
    await answered();

    expect(await screen.findByText(expected)).toBeInTheDocument();
    // Not merely non-empty: the page frame is there.
    expect(container.querySelector('.plugins-page')).not.toBeNull();
  });

  // The one tab that does leave, and it must leave rather than render here.
  it('moves ?tab=mcp to /apps', async () => {
    renderPluginsRoute('/plugins?tab=mcp');

    await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent('/apps'));
    expect(screen.getByTestId('address')).toHaveTextContent('tab=mcp');
    expect(screen.queryByText('your connectors')).not.toBeInTheDocument();
  });

  // The old spelling of the same tab, and a bare detail whose kind names it.
  it.each(['/plugins?tab=servers', '/plugins?detail=server:foo'])(
    'moves %s to /apps',
    async (entry) => {
      renderPluginsRoute(entry);

      await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent('/apps'));
      expect(screen.getByTestId('address')).toHaveTextContent('tab=mcp');
    },
  );
});
