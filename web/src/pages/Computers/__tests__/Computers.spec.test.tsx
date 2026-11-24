import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router';

import { closeComputerSpec, useComputersPanel } from '@/pages/ChatAgent/hooks/computerPanelStore';
import { renderWithProviders } from '@/test/utils';
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
vi.mock('@/pages/ChatAgent/hooks/useComputerActions', () => ({ useComputerActions: () => ({ power: {} }) }));
vi.mock('@/hooks/useAllWorkspaces', () => ({ useAllWorkspaces: () => ({}) }));
vi.mock('../useDesktopSession', () => ({ useDesktopSession: () => ({ state: { status: 'idle' } }) }));
vi.mock('@/pages/ChatAgent/components/ComputersDialogHost', () => ({
  default: function SpecDialogTarget() {
    const { specComputerId } = useComputersPanel();
    return specComputerId ? <output aria-label="Spec target">{specComputerId}</output> : null;
  },
}));

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

afterEach(() => { act(closeComputerSpec); });

describe('cloud computer specs', () => {
  it.each(['/computers', '/computers/research-box/desktop'])('shows the configured hardware and opens the shared dialog on %s', async (route) => {
    renderPage([hosted], [provider], route);
    expect(screen.getByText('4 vCPU · 8 GB RAM · 30 GB disk')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Change spec' }));
    expect(await screen.findByLabelText('Spec target')).toHaveTextContent('research-box');
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
    expect(await screen.findByLabelText('Spec target')).toHaveTextContent('research-box');
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
