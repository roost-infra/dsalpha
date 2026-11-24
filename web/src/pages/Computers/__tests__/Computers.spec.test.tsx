import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router';

import { closeComputerSpec } from '@/pages/ChatAgent/hooks/computerPanelStore';
import { renderWithProviders } from '@/test/utils';
import { runAuthResets } from '@/lib/authResets';
import type { Computer, ComputerProviderOption, ComputerSpecChange } from '@/types/api';

import Computers from '../Computers';

const fixtures = vi.hoisted(() => ({
  computers: [] as Computer[],
  providers: [] as ComputerProviderOption[],
}));

vi.mock('@/pages/ChatAgent/hooks/useComputers', () => ({
  useComputers: () => ({ data: { computers: fixtures.computers } }),
  useComputerProviders: () => ({ data: { providers: fixtures.providers } }),
  useComputerStatusFanout: vi.fn(),
}));
vi.mock('@/pages/ChatAgent/hooks/useComputerActions', () => ({ useComputerActions: () => ({ power: {}, spec: {} }) }));
vi.mock('@/pages/ChatAgent/hooks/useTierQuota', () => ({ useTierQuota: () => ({}) }));
vi.mock('@/hooks/useAllWorkspaces', () => ({ useAllWorkspaces: () => ({}) }));
vi.mock('../useDesktopSession', () => ({ useDesktopSession: () => ({ state: { status: 'idle' } }) }));

const hosted: Computer = {
  computer_id: 'research-box',
  user_id: 'owner',
  kind: 'daytona',
  name: 'Research box',
  status: 'running',
  resource_tier: 'performance',
  is_always_on: false,
  is_primary: true,
  root_dir: '/workspace',
  ssh: null,
};

const provider: ComputerProviderOption = {
  kind: 'daytona', is_default: true, allowed: true,
  tiers: [
    { tier: 'performance', cpu: 4, memory_gib: 8, disk_gib: 30 },
    { tier: 'max', cpu: 8, memory_gib: 16, disk_gib: 60 },
  ],
};

const resize: ComputerSpecChange = {
  from_tier: 'performance', target_tier: 'max', state: 'in_progress', started_at: '2026-11-25T00:00:00Z',
};

function renderPage(computers: Computer[], providers: ComputerProviderOption[] = [provider], route = '/computers') {
  fixtures.computers = computers;
  fixtures.providers = providers;
  return renderWithProviders(
    <Routes>
      <Route path="/computers" element={<Computers />} />
      <Route path="/computers/:computerId/desktop" element={<Computers />} />
    </Routes>,
    { route },
  );
}

const fullscreenDescriptor = Object.getOwnPropertyDescriptor(document, 'fullscreenElement');
const exitDescriptor = Object.getOwnPropertyDescriptor(document, 'exitFullscreen');

beforeEach(() => {
  runAuthResets();
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => null });
  Object.defineProperty(document, 'exitFullscreen', { configurable: true, writable: true, value: vi.fn() });
});

afterEach(() => {
  act(closeComputerSpec);
  vi.restoreAllMocks();
  if (fullscreenDescriptor) Object.defineProperty(document, 'fullscreenElement', fullscreenDescriptor);
  else Reflect.deleteProperty(document, 'fullscreenElement');
  if (exitDescriptor) Object.defineProperty(document, 'exitFullscreen', exitDescriptor);
  else Reflect.deleteProperty(document, 'exitFullscreen');
});

describe('cloud computer specs', () => {
  it.each(['Change spec', 'Details'])('exits fullscreen before opening %s in the real host', async (label) => {
    renderPage([{ ...hosted, spec_change: label === 'Details' ? resize : null }], [provider], '/computers/research-box/desktop');
    const button = screen.getByRole('button', { name: label });
    const section = button.closest('section')!;
    let fullscreenElement: Element | null = section;
    vi.spyOn(document, 'fullscreenElement', 'get').mockImplementation(() => fullscreenElement);
    let finishExit!: () => void;
    const exit = vi.spyOn(document, 'exitFullscreen').mockImplementation(() => new Promise<void>((resolve) => {
      finishExit = () => { fullscreenElement = null; resolve(); };
    }));

    await userEvent.click(button);
    expect(exit).toHaveBeenCalledOnce();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await act(async () => { finishExit(); });
    const dialog = await screen.findByRole('dialog', { name: 'Change spec for Research box' });
    expect(document.fullscreenElement).toBeNull();
    expect(section.contains(dialog)).toBe(false);
  });

  it('keeps the dialog closed and reports a rejected fullscreen exit, then allows retry', async () => {
    renderPage([hosted], [provider], '/computers/research-box/desktop');
    const button = screen.getByRole('button', { name: 'Change spec' });
    vi.spyOn(document, 'fullscreenElement', 'get').mockReturnValue(button.closest('section'));
    const exit = vi.spyOn(document, 'exitFullscreen').mockRejectedValue(new Error('Denied'));
    await userEvent.click(button);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    exit.mockResolvedValue();
    await userEvent.click(button);
    expect(await screen.findByRole('dialog', { name: 'Change spec for Research box' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each(['/computers', '/computers/research-box/desktop'])('shows the configured hardware and opens the shared dialog on %s', async (route) => {
    renderPage([hosted], [provider], route);
    expect(screen.getByText('4 vCPU · 8 GB RAM · 30 GB disk')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Change spec' }));
    expect(await screen.findByRole('dialog', { name: 'Change spec for Research box' })).toBeInTheDocument();
  });

  it('leaves sizing out of SSH computers and hides the action where there are no other offered tiers', () => {
    renderPage(
      [hosted, { ...hosted, computer_id: 'own-box', name: 'Own box', kind: 'ssh' }],
      [{ ...provider, tiers: provider.tiers?.slice(0, 1) }],
    );
    const ssh = within(screen.getByRole('article', { name: 'Own box' }));
    expect(ssh.queryByText('Spec')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change spec' })).not.toBeInTheDocument();
  });

  it('shows resize progress without displaying the target hardware as current', async () => {
    renderPage([{ ...hosted, resource_tier: 'max', spec_change: resize }]);
    expect(screen.getByText(/^Upgrading to /)).toBeInTheDocument();
    expect(screen.queryByText(/8 vCPU/)).not.toBeInTheDocument();
    const specDetails = within(screen.getByText('Spec').parentElement!);
    await userEvent.click(specDetails.getByRole('button', { name: 'Details' }));
    expect(await screen.findByRole('dialog', { name: 'Change spec for Research box' })).toBeInTheDocument();
  });

  it('leaves hardware unconfirmed after an interrupted resize and offers a retry', () => {
    renderPage([{
      ...hosted, resource_tier: 'max',
      spec_change: { ...resize, state: 'failed', error: { code: 'interrupted', message: 'Interrupted', files: [] } },
    }]);
    expect(screen.getByText('Current spec unconfirmed')).toBeInTheDocument();
    expect(screen.queryByText(/vCPU/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Change spec' })).toBeEnabled();
  });
});
