import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import AccountMenu from '../AccountMenu';

const navigate = vi.hoisted(() => vi.fn());

vi.mock('react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router')>()),
  useNavigate: () => navigate,
  useLocation: () => ({ pathname: '/dashboard' }),
}));

vi.mock('@/config/hostMode', () => ({ isPlatformMode: true }));
vi.mock('@/config/supportLinks', () => ({
  INTEGRATIONS_URL: '/account/integrations',
}));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ logout: vi.fn() }) }));
vi.mock('@/hooks/useUser', () => ({
  useUser: () => ({
    user: {
      display_name: 'Test User',
      email: 'test@example.com',
      plan_display_name: 'Free',
    },
  }),
}));

describe('AccountMenu usage and plan', () => {
  beforeEach(() => navigate.mockReset());

  it('opens Plan & usage in Settings instead of the account portal', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AccountMenu variant="rail" />);

    await user.click(screen.getByRole('button', { name: /account menu/i }));
    await user.click(screen.getByText('Usage & Plan'));

    expect(navigate).toHaveBeenCalledWith('/settings?tab=plan');
  });
});
