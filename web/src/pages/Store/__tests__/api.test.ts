// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from '@/api/client';
import {
  getMarketBot,
  getMyMarketInstalls,
  installMarketBot,
  listMarketBots,
} from '../api';

const get = api.get as unknown as ReturnType<typeof vi.fn>;
const post = api.post as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe('the Bot market API', () => {
  it('sends only the filters that were set', async () => {
    get.mockResolvedValue({ data: { bots: [], categories: [] } });
    await listMarketBots({ q: '  macro  ', category: 'research' });

    expect(get).toHaveBeenCalledWith('/api/v1/market/bots', {
      params: { q: 'macro', category: 'research' },
    });

    get.mockClear();
    await listMarketBots();
    expect(get).toHaveBeenCalledWith('/api/v1/market/bots', undefined);
  });

  it('reads one detail and the caller installs', async () => {
    get.mockResolvedValueOnce({ data: { slug: 'macro-bot' } });
    await getMarketBot('macro-bot');
    expect(get).toHaveBeenCalledWith('/api/v1/market/bots/macro-bot');

    get.mockResolvedValueOnce({ data: { installs: [] } });
    await getMyMarketInstalls();
    expect(get).toHaveBeenCalledWith('/api/v1/market/me/installs');
  });

  it('posts the workspace and name an install wrote', async () => {
    const answer = {
      install_id: 'install-1',
      bot: { bot_id: 'bot-1', name: 'Macro desk', workspace_id: 'ws-1' },
    };
    post.mockResolvedValue({ data: answer });
    const result = await installMarketBot('macro-bot', {
      workspace_id: 'ws-1',
      name: 'Macro desk',
    });

    expect(post).toHaveBeenCalledWith('/api/v1/market/bots/macro-bot/install', {
      workspace_id: 'ws-1',
      name: 'Macro desk',
    });
    expect(result).toEqual(answer);
  });
});
