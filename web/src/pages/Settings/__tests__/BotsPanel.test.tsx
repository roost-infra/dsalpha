/**
 * The Bots settings section: the list grouped by workspace, the derived Chief
 * of Staff drawn read-only, and the three writes the section offers. The hooks
 * are stubbed so the assertions are about what the section asks them to do,
 * not about React Query again (that contract lives in useBots.test.tsx).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import type { BotInfo } from '@/api/bots';
import type { Workspace } from '@/types/api';
import { renderWithProviders } from '@/test/utils';

const h = vi.hoisted(() => ({
  bots: [] as BotInfo[],
  workspaces: [] as Workspace[],
  create: vi.fn(async (_input: unknown) => ({})),
  update: vi.fn(async (_args: unknown) => ({})),
  remove: vi.fn(async (_botId: string) => ({})),
  toast: vi.fn(),
}));

vi.mock('@/hooks/useBots', () => ({
  useBots: () => ({
    data: { bots: h.bots, max_bots: 20 },
    isLoading: false,
    isError: false,
    error: null,
    refetch: () => undefined,
  }),
  useCreateBot: () => ({ mutateAsync: h.create, mutate: h.create, isPending: false, error: null }),
  useUpdateBot: () => ({ mutateAsync: h.update, mutate: h.update, isPending: false, error: null }),
  useDeleteBot: () => ({ mutateAsync: h.remove, mutate: h.remove, isPending: false, error: null }),
}));

vi.mock('@/hooks/useAllWorkspaces', () => ({
  useAllWorkspaces: () => ({
    data: { workspaces: h.workspaces, total: h.workspaces.length },
    isLoading: false,
  }),
}));

vi.mock('@/components/ui/use-toast', () => ({
  useToast: () => ({ toast: h.toast }),
}));

import { BotsPanel } from '../panels/BotsPanel';

const HOME: Workspace = { workspace_id: 'ws-home', name: 'Home', is_home: true };
const RESEARCH: Workspace = { workspace_id: 'ws-research', name: 'Research', is_home: false };

function bot(overrides: Partial<BotInfo> & Pick<BotInfo, 'bot_id' | 'name' | 'role' | 'workspace_id'>): BotInfo {
  return {
    user_id: 'user-1',
    persona: '',
    avatar: {},
    provider: null,
    model: null,
    skills: [],
    tools_allow: [],
    tools_deny: [],
    approval: 'ask',
    memory_scopes: ['workspace'],
    status: 'active',
    primary_thread_id: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

const CHIEF = bot({ bot_id: 'bot-cos', name: 'Chief of Staff', role: 'chief_of_staff', workspace_id: 'ws-home' });
const ANALYST = bot({ bot_id: 'bot-1', name: 'Macro analyst', role: 'analyst', workspace_id: 'ws-research' });

function renderPanel() {
  return renderWithProviders(<BotsPanel />);
}

beforeEach(() => {
  h.bots = [CHIEF, ANALYST];
  h.workspaces = [HOME, RESEARCH];
  h.create.mockReset();
  h.create.mockResolvedValue({});
  h.update.mockReset();
  h.update.mockResolvedValue({});
  h.remove.mockReset();
  h.remove.mockResolvedValue({});
  h.toast.mockReset();
});

describe('BotsPanel list', () => {
  it('groups every bot under its workspace', () => {
    renderPanel();

    expect(screen.getByRole('heading', { name: 'Your bots' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Home' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Research' })).toBeInTheDocument();
    expect(screen.getByText('Macro analyst')).toBeInTheDocument();
    expect(screen.getByText('Chief of Staff')).toBeInTheDocument();
  });

  it('draws the derived Chief of Staff read-only, with no row actions', () => {
    renderPanel();

    const row = screen.getByText('Chief of Staff').closest('.settings-row');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText('Read-only')).toBeInTheDocument();
    expect(within(row as HTMLElement).queryByRole('button')).toBeNull();
    // Every row wears its BotMark, the derived one included.
    expect((row as HTMLElement).querySelector('[data-bot-mark]')).not.toBeNull();
  });

  it('offers edit, pause and delete on an analyst row', () => {
    renderPanel();

    const row = screen.getByText('Macro analyst').closest('.settings-row') as HTMLElement;
    expect(within(row).getByRole('button', { name: 'Delete Macro analyst' })).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Edit Macro analyst' })).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Pause Macro analyst' })).toBeInTheDocument();
  });

  it('explains a workspace needs a bot when there are none', () => {
    h.bots = [];
    renderPanel();

    expect(screen.getByText('No bots yet')).toBeInTheDocument();
    expect(screen.getByText(/A workspace needs a bot/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New bot' })).toBeEnabled();
  });
});

describe('BotsPanel writes', () => {
  it('creates a bot in the workspace the dialog picks', async () => {
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'New bot' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Rates analyst' } });
    // Only Research is offered: Home holds the derived Chief of Staff.
    expect(screen.getByLabelText('Workspace')).toHaveValue('ws-research');
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(h.create).toHaveBeenCalledWith({
      workspace_id: 'ws-research',
      name: 'Rates analyst',
      role: 'analyst',
      persona: '',
      provider: null,
      model: null,
      approval: 'ask',
    }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('edits the name, persona, model and approval of a bot', async () => {
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Macro analyst' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Macro strategist' } });
    // The approval is stored and shown for now; the dialog says so.
    expect(screen.getByText(/v1 does not auto-approve/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(h.update).toHaveBeenCalledWith({
      botId: 'bot-1',
      patch: { name: 'Macro strategist', persona: '', model: null, approval: 'ask' },
    }));
  });

  it('edits the skill and tool lists and memory scopes, keeping a scope it does not show', async () => {
    h.bots = [CHIEF, { ...ANALYST, memory_scopes: ['workspace', 'legacy'] }];
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Macro analyst' }));
    fireEvent.change(screen.getByLabelText('Skills'), { target: { value: 'macro, rates, macro' } });
    fireEvent.change(screen.getByLabelText('Allowed tools'), { target: { value: ' web_search , quote ' } });
    fireEvent.change(screen.getByLabelText('Blocked tools'), { target: { value: 'trading' } });
    fireEvent.click(screen.getByLabelText('User memory'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(h.update).toHaveBeenCalledWith({
      botId: 'bot-1',
      patch: {
        name: 'Macro analyst',
        persona: '',
        model: null,
        approval: 'ask',
        skills: ['macro', 'rates'],
        tools_allow: ['web_search', 'quote'],
        tools_deny: ['trading'],
        // The scope this UI does not offer is carried through untouched.
        memory_scopes: ['workspace', 'legacy', 'user'],
      },
    }));
  });

  it('saves a chosen colour, shape and glyph as the avatar', async () => {
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Macro analyst' }));
    fireEvent.click(screen.getByRole('button', { name: 'Mark' }));
    fireEvent.click(screen.getByRole('button', { name: 'Teal' }));
    fireEvent.change(screen.getByLabelText('Shape'), { target: { value: 'hex' } });
    fireEvent.change(screen.getByLabelText('Glyph (optional)'), { target: { value: 'Z' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(h.update).toHaveBeenCalledWith({
      botId: 'bot-1',
      patch: expect.objectContaining({
        avatar: { kind: 'mark', shape: 'hex', color: 'teal', glyph: 'Z' },
      }),
    }));
  });

  it('leaves an untouched avatar out of the patch', async () => {
    h.bots = [CHIEF, { ...ANALYST, avatar: { kind: 'image', url: 'https://example.com/a.png' } }];
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Macro analyst' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Renamed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(h.update).toHaveBeenCalled());
    const patch = (h.update.mock.calls[0][0] as { patch: Record<string, unknown> }).patch;
    expect(patch).not.toHaveProperty('avatar');
  });

  it('keeps keys the avatar UI does not own when one of its fields changes', async () => {
    h.bots = [CHIEF, { ...ANALYST, avatar: { kind: 'mark', shape: 'circle', color: 'blue', note: 'keep' } }];
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Macro analyst' }));
    fireEvent.click(screen.getByRole('button', { name: 'Rose' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(h.update).toHaveBeenCalledWith({
      botId: 'bot-1',
      patch: expect.objectContaining({
        avatar: { note: 'keep', kind: 'mark', shape: 'circle', color: 'rose' },
      }),
    }));
  });

  it('uses the automatic mark when asked to reset', async () => {
    h.bots = [CHIEF, { ...ANALYST, avatar: { kind: 'emoji', emoji: '🦊' } }];
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Macro analyst' }));
    fireEvent.click(screen.getByRole('button', { name: 'Use automatic mark' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(h.update).toHaveBeenCalledWith({
      botId: 'bot-1',
      patch: expect.objectContaining({ avatar: {} }),
    }));
  });

  it('pauses an active bot through the status write', () => {
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Pause Macro analyst' }));

    expect(h.update).toHaveBeenCalledWith(
      { botId: 'bot-1', patch: { status: 'paused' } },
      expect.objectContaining({ onError: expect.any(Function) }),
    );
  });

  it('deletes a bot only after the confirmation dialog', async () => {
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Delete Macro analyst' }));
    expect(screen.getByRole('heading', { name: 'Delete bot' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Delete bot' }));

    await waitFor(() => expect(h.remove).toHaveBeenCalledWith('bot-1', expect.anything()));
  });
});
