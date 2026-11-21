import { describe, it, expect, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/utils';
import { BotCard } from '../components/BotCard';
import type { MarketBotCard } from '../api';

const BOT: MarketBotCard = {
  slug: 'macro-desk',
  name: 'Macro Desk',
  summary: 'Tracks rates, central banks and the dollar.',
  category: 'research',
  tags: ['macro', 'rates'],
  version: '1.2.0',
  featured: true,
  installed: true,
};

describe('BotCard', () => {
  it('draws the marks a reader scans for and opens the detail', () => {
    const onOpen = vi.fn();
    renderWithProviders(
      <BotCard bot={BOT} categoryLabel="Research" onOpen={onOpen} />,
    );

    expect(screen.getByText('Macro Desk')).toBeInTheDocument();
    expect(screen.getByText(BOT.summary)).toBeInTheDocument();
    expect(screen.getByText('Research')).toBeInTheDocument();
    // The version is drawn through the catalog's template, not as a bare number.
    expect(screen.getByText('v1.2.0')).toBeInTheDocument();
    expect(screen.getByText('Featured')).toBeInTheDocument();
    expect(screen.getByText('Installed')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Open Macro Desk' }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it('leaves off the badges a plain card does not have', () => {
    renderWithProviders(
      <BotCard
        bot={{ ...BOT, featured: false, installed: false, tags: [] }}
        onOpen={() => {}}
      />,
    );

    expect(screen.queryByText('Featured')).not.toBeInTheDocument();
    expect(screen.queryByText('Installed')).not.toBeInTheDocument();
    expect(screen.queryByText('v1.2.0')).toBeInTheDocument();
  });
});
