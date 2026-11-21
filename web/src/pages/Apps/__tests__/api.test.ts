// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({
  api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

import { api } from '@/api/client';
import {
  clearComposioKey,
  connectConnectedApp,
  disconnectConnectedAccount,
  getConnectedApps,
  saveComposioKey,
} from '../api';

const get = api.get as unknown as ReturnType<typeof vi.fn>;
const put = api.put as unknown as ReturnType<typeof vi.fn>;
const post = api.post as unknown as ReturnType<typeof vi.fn>;
const del = api.delete as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  get.mockReset();
  put.mockReset();
  post.mockReset();
  del.mockReset();
});

describe('connected apps API', () => {
  it('reads the one status payload', async () => {
    get.mockResolvedValue({ data: { configured: false, using_deployment_key: false, apps: [] } });
    await getConnectedApps();
    expect(get).toHaveBeenCalledWith('/api/v1/connected-apps');
  });

  it('saves the key to the vault through the setup endpoint', async () => {
    put.mockResolvedValue({ data: { configured: true } });
    await saveComposioKey('ak_live');
    expect(put).toHaveBeenCalledWith('/api/v1/connected-apps/key', { api_key: 'ak_live' });

    del.mockResolvedValue({ data: { configured: false } });
    await clearComposioKey();
    expect(del).toHaveBeenCalledWith('/api/v1/connected-apps/key');
  });

  it('returns the OAuth link for one app and disconnects one account', async () => {
    post.mockResolvedValue({ data: { url: 'https://connect.example/oauth' } });
    const link = await connectConnectedApp('github', 'work');
    expect(link.url).toBe('https://connect.example/oauth');
    expect(post).toHaveBeenCalledWith('/api/v1/connected-apps/github/connect', {
      alias: 'work',
    });

    del.mockResolvedValue({ data: { ok: true } });
    await disconnectConnectedAccount('ca-1');
    expect(del).toHaveBeenCalledWith('/api/v1/connected-apps/accounts/ca-1');
  });
});
