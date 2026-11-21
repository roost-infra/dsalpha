import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/utils';

const h = vi.hoisted(() => ({
  thread: { bot_id: 'bot-1' } as { bot_id?: string } | undefined,
  bot: undefined as unknown,
  connected: undefined as unknown,
  navigate: vi.fn(),
}));

vi.mock('@tanstack/react-query', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-query')>()),
  useQuery: () => ({ data: h.thread }),
}));

vi.mock('react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router')>()),
  useNavigate: () => h.navigate,
}));

vi.mock('@/hooks/useBots', () => ({
  useBot: () => ({ data: h.bot }),
}));

vi.mock('@/pages/Apps/hooks', () => ({
  useConnectedApps: () => ({ data: h.connected }),
}));

import { ConnectorConnectCard } from '../ConnectorConnectCard';

const app = (slug: string, name: string, accounts: unknown[] = []) => ({
  slug,
  name,
  description: '',
  logo: null,
  categories: [],
  connected: accounts.length > 0,
  accounts,
});

beforeEach(() => {
  h.navigate.mockReset();
  h.thread = { bot_id: 'bot-1' };
  h.bot = { connector_tools: { github: { tools: '*' } } };
  h.connected = { apps: [app('github', 'GitHub')] };
});

describe('ConnectorConnectCard', () => {
  it('names the granted app that has no account and opens Connected apps', () => {
    renderWithProviders(<ConnectorConnectCard threadId="thread-1" />);

    expect(screen.getByTestId('connector-connect-card')).toBeInTheDocument();
    expect(screen.getByText('Connect GitHub to use it here')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Connect app/ }));
    expect(h.navigate).toHaveBeenCalledWith('/apps');
  });

  it('stays away once the account is connected', () => {
    h.connected = { apps: [app('github', 'GitHub', [{ id: 'ca-1', status: 'ACTIVE' }])] };
    renderWithProviders(<ConnectorConnectCard threadId="thread-1" />);
    expect(screen.queryByTestId('connector-connect-card')).not.toBeInTheDocument();
  });

  it('says nothing for a bot with no grant map', () => {
    h.bot = { connector_tools: {} };
    renderWithProviders(<ConnectorConnectCard threadId="thread-1" />);
    expect(screen.queryByTestId('connector-connect-card')).not.toBeInTheDocument();
  });
});
