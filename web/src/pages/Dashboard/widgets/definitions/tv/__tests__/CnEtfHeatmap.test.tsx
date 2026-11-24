import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/quotes', () => ({
  useQuotes: () => ({
    quotes: {
      '510300.SH': { price: 4.2, change_percent: 1.25, volume: 9_000_000 },
      '510500.SH': { price: 5.6, change_percent: -0.8, volume: 4_000_000 },
    },
    isLoading: false,
  }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

import CnEtfHeatmap from '../CnEtfHeatmap';

describe('CnEtfHeatmap', () => {
  it('paints A-share ETFs with China up/down colours', () => {
    const { container } = render(<CnEtfHeatmap />);
    expect(screen.getByTestId('cn-etf-heatmap')).toBeInTheDocument();
    expect(container.querySelector('.cn-etf-cell.is-up')).toBeTruthy();
    expect(container.querySelector('.cn-etf-cell.is-down')).toBeTruthy();
    expect(screen.getByText('+1.25%')).toBeInTheDocument();
    expect(screen.getByText('-0.80%')).toBeInTheDocument();
  });
});
