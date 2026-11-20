import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import i18n from '@/i18n';

// The header's symbol search hits the network on a timer; the switch under
// test has nothing to do with it.
vi.mock('@/hooks/useSymbolSearch', () => ({
  useSymbolSearch: () => ({ hits: [], loading: false }),
}));
vi.mock('@/hooks/useIsMobile', () => ({ useIsMobile: () => false }));

import DashboardHeader from '../DashboardHeader';

function renderHeader(props: Parameters<typeof DashboardHeader>[0]) {
  return render(
    <MemoryRouter>
      <DashboardHeader {...props} />
    </MemoryRouter>,
  );
}

describe('DashboardHeader market switch', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US');
  });

  it('marks the active region and reports the other one when clicked', () => {
    const onMarketChange = vi.fn();
    renderHeader({ market: 'us', onMarketChange });

    const us = screen.getByRole('button', { name: 'US' });
    const cn = screen.getByRole('button', { name: 'A-shares' });
    expect(us.getAttribute('aria-pressed')).toBe('true');
    expect(cn.getAttribute('aria-pressed')).toBe('false');

    fireEvent.click(cn);
    expect(onMarketChange).toHaveBeenCalledWith('cn');

    // The region is a state of the page, not of the button: the header keeps
    // showing the region it was handed until the write lands.
    expect(us.getAttribute('aria-pressed')).toBe('true');
  });

  it('renders no switch when the page does not own a region', () => {
    renderHeader({});
    expect(screen.queryByRole('group', { name: 'Market region' })).toBeNull();
  });

  it('renders no switch while the market plugin is off', () => {
    renderHeader({ marketEnabled: false, market: 'us', onMarketChange: vi.fn() });
    expect(screen.queryByRole('group', { name: 'Market region' })).toBeNull();
  });
});
