import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/utils';

vi.mock('../hooks', () => ({
  useConnectedApps: vi.fn(),
  useSaveComposioKey: vi.fn(),
  useConnectConnectedApp: vi.fn(),
  useDisconnectConnectedAccount: vi.fn(),
}));

import {
  useConnectedApps,
  useConnectConnectedApp,
  useDisconnectConnectedAccount,
  useSaveComposioKey,
} from '../hooks';
import Apps from '../Apps';

const status = (overrides: Record<string, unknown> = {}) => ({
  data: {
    configured: true,
    using_deployment_key: false,
    apps: [
      {
        slug: 'github',
        name: 'GitHub',
        description: 'Issues, pull requests and code',
        logo: null,
        categories: ['Developer tools'],
        connected: false,
        accounts: [],
      },
      {
        slug: 'gmail',
        name: 'Gmail',
        description: 'Read and send email',
        logo: null,
        categories: [],
        connected: true,
        accounts: [{ id: 'ca-1', alias: 'work', status: 'ACTIVE' }],
      },
    ],
    ...overrides,
  },
  isLoading: false,
  isError: false,
  isFetching: false,
  error: null,
  refetch: vi.fn(),
});

const asQuery = (value: unknown) => value as never;
const saveMutate = vi.fn();
const connectMutate = vi.fn();
const disconnectMutate = vi.fn();

beforeEach(() => {
  saveMutate.mockReset();
  connectMutate.mockReset();
  disconnectMutate.mockReset();
  vi.mocked(useConnectedApps).mockReturnValue(asQuery(status()));
  vi.mocked(useSaveComposioKey).mockReturnValue(
    asQuery({ mutateAsync: saveMutate, isPending: false }),
  );
  vi.mocked(useConnectConnectedApp).mockReturnValue(
    asQuery({ mutate: connectMutate, isPending: false }),
  );
  vi.mocked(useDisconnectConnectedAccount).mockReturnValue(
    asQuery({ mutate: disconnectMutate, isPending: false }),
  );
});

describe('/apps', () => {
  it('draws connected accounts and starts a connection', async () => {
    renderWithProviders(<Apps />);

    expect(screen.getByRole('heading', { name: 'Connected apps' })).toBeInTheDocument();
    expect(screen.getByText('Connected')).toBeInTheDocument();
    expect(screen.getByText('work')).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: 'Connect' })[0]);
    await waitFor(() => expect(connectMutate).toHaveBeenCalled());
    expect(connectMutate.mock.calls[0][0]).toEqual({ slug: 'github' });
  });

  it('disconnects one account without touching the others', () => {
    renderWithProviders(<Apps />);
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect work' }));
    expect(disconnectMutate).toHaveBeenCalledWith('ca-1', expect.anything());
  });

  it('asks for a project key before it shows the catalog', async () => {
    vi.mocked(useConnectedApps).mockReturnValue(
      asQuery(status({ configured: false, apps: [] })),
    );
    saveMutate.mockResolvedValue({ configured: true, apps: [] });
    renderWithProviders(<Apps />);

    expect(screen.queryByText('GitHub')).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('ak_...'), {
      target: { value: 'ak_live' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save key' }));
    await waitFor(() => expect(saveMutate).toHaveBeenCalledWith('ak_live'));
  });
});
