import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import type { MarketBotDetail, MarketBotListResponse, MarketInstallsResponse } from '../api';

vi.mock('../hooks', () => ({
  useMarketBots: vi.fn(),
  useMyMarketInstalls: vi.fn(),
  useMarketBot: vi.fn(),
  useInstallMarketBot: vi.fn(),
}));

vi.mock('@/hooks/useAllWorkspaces', () => ({
  useAllWorkspaces: vi.fn(),
}));

import { useAllWorkspaces } from '@/hooks/useAllWorkspaces';
import {
  useInstallMarketBot,
  useMarketBots,
  useMarketBot,
  useMyMarketInstalls,
} from '../hooks';
import Store from '../Store';

const LIST: MarketBotListResponse = {
  bots: [
    {
      slug: 'macro-desk',
      name: 'Macro Desk',
      summary: 'Tracks rates and the dollar.',
      category: 'research',
      tags: ['macro'],
      version: '1.2.0',
      featured: false,
      installed: false,
    },
  ],
  categories: [{ id: 'research', label: 'Research' }],
};

const DETAIL: MarketBotDetail = {
  slug: 'macro-desk',
  name: 'Macro Desk',
  summary: 'Tracks rates and the dollar.',
  description: 'A macro analyst.',
  category: 'research',
  tags: ['macro'],
  version: '1.2.0',
  featured: false,
  persona: 'You track rates.',
  tools: ['web_search'],
  skills: ['macro'],
  installs: [],
};

const INSTALLS: MarketInstallsResponse = {
  installs: [
    {
      install_id: 'install-1',
      slug: 'macro-desk',
      name: 'Macro Desk',
      version: '1.2.0',
      workspace_id: 'ws-1',
      workspace_name: 'Research',
      bot_id: 'bot-1',
      created_at: '2026-11-20T00:00:00Z',
    },
  ],
};

const HOME = { workspace_id: 'home-1', name: 'Home', is_home: true };
const RESEARCH = { workspace_id: 'ws-1', name: 'Research', is_home: false };
const installMutate = vi.fn();

const asQuery = (value: unknown) => value as never;

beforeEach(() => {
  installMutate.mockReset();
  installMutate.mockResolvedValue({
    install_id: 'install-1',
    bot: { bot_id: 'bot-1', name: 'Macro Desk', workspace_id: 'ws-1' },
  });
  vi.mocked(useAllWorkspaces).mockReturnValue(
    asQuery({
      data: { workspaces: [HOME, RESEARCH], total: 2 },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    }),
  );
  vi.mocked(useInstallMarketBot).mockReturnValue(
    asQuery({ mutateAsync: installMutate, isPending: false, error: null }),
  );
  vi.mocked(useMarketBots).mockReturnValue(
    asQuery({ data: LIST, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
  );
  vi.mocked(useMyMarketInstalls).mockReturnValue(
    asQuery({ data: INSTALLS, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
  );
  vi.mocked(useMarketBot).mockReturnValue(
    asQuery({ data: DETAIL, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
  );
});

describe('/store', () => {
  it('draws the grid and opens a bot detail', async () => {
    renderWithProviders(<Store />);

    expect(screen.getByRole('heading', { name: 'Bot Store' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open Macro Desk' }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Macro Desk' })).toBeInTheDocument(),
    );
    expect(screen.getByText('You track rates.')).toBeInTheDocument();
    expect(screen.getByText('web_search')).toBeInTheDocument();
  });

  it('install dialog lists non-Home workspaces and posts the chosen name', async () => {
    renderWithProviders(<Store />);

    fireEvent.click(screen.getByRole('button', { name: 'Open Macro Desk' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Install' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Install Macro Desk')).toBeInTheDocument();
    expect(within(dialog).queryByRole('option', { name: 'Home' })).not.toBeInTheDocument();
    expect(within(dialog).getByRole('option', { name: 'Research' })).toBeInTheDocument();
    expect(within(dialog).getByDisplayValue('Macro Desk')).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Install' }));
    await waitFor(() =>
      expect(installMutate).toHaveBeenCalledWith({
        slug: 'macro-desk',
        input: { workspace_id: 'ws-1', name: 'Macro Desk' },
      }),
    );
  });

  it('switches to the installed tab and reads the caller installs', () => {
    renderWithProviders(<Store />);

    fireEvent.click(screen.getByRole('tab', { name: 'Installed' }));
    expect(useMyMarketInstalls).toHaveBeenLastCalledWith(true);
    expect(screen.getByRole('button', { name: /Macro Desk/ })).toBeInTheDocument();
  });
});
