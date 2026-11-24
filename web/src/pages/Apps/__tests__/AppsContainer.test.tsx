/**
 * `/apps` as the two-section container: the connectors surface reached through
 * it, and a rail whose links stay on the page that hosts them.
 *
 * The section bodies have their own suites, so this is about the frame — which
 * section a URL opens, and that a rail entry on `/apps` names `/apps` rather
 * than the `/plugins` tab that section used to live on.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { useLocation } from 'react-router';
import { renderWithProviders } from '@/test/utils';
import { getMarketplace } from '@/pages/ChatAgent/utils/api/marketplace';

import Apps from '../Apps';

vi.mock('@/pages/ChatAgent/utils/api/marketplace', () => ({ getMarketplace: vi.fn() }));

// The frame is under test; the sections and their data are not.
vi.mock('@/pages/Plugins/components/shell/useShellData', () => ({ useShellData: () => ({}) }));
vi.mock('@/pages/Plugins/components/WorkspacesLoadNote', () => ({ WorkspacesLoadNote: () => null }));
vi.mock('@/pages/Plugins/components/McpServers', () => ({ McpServers: () => <p>your connectors</p> }));

function Address() {
  return <output data-testid="address">{useLocation().search}</output>;
}

function renderPage(route: string) {
  return renderWithProviders(
    <>
      <Apps />
      <Address />
    </>,
    { route },
  );
}

beforeEach(() => {
  vi.mocked(getMarketplace).mockReset();
  // No catalog: keeps `useCatalogOn` from holding the header's Add menu open on
  // a `view=discover` rewrite this test is not about.
  vi.mocked(getMarketplace).mockResolvedValue({
    configured: false,
    name: null,
    description: null,
    url: null,
    vocabulary: { assets: [], regions: [], data: [] },
    entries: [],
  });
});

describe('the /apps container', () => {
  it('reaches the connectors surface under ?tab=mcp', async () => {
    renderPage('/apps?tab=mcp');
    expect(await screen.findByText('your connectors')).toBeInTheDocument();
    expect(screen.getByTestId('address')).toHaveTextContent('?tab=mcp');
  });

  it('keeps every rail link on /apps, and offers only the sections it hosts', async () => {
    renderPage('/apps?tab=mcp');

    expect(await screen.findByRole('link', { name: /managed apps/i })).toHaveAttribute(
      'href',
      '/apps?tab=apps',
    );
    expect(screen.getByRole('link', { name: /connectors/i })).toHaveAttribute(
      'href',
      '/apps?tab=mcp',
    );
    // A section this page does not host is not offered here, even though the
    // other container page draws it.
    expect(screen.queryByRole('link', { name: /^skills$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^subagents$/i })).not.toBeInTheDocument();
  });
});
