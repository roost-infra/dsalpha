import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { MarketRedirect } from '../MarketRedirect';

function CurrentLocation() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>;
}

describe('legacy /market links', () => {
  it('keeps the market query and hash on the plugin route', () => {
    render(
      <MemoryRouter initialEntries={['/market?symbol=GSPC&tf=1D&returnTo=%2Fdashboard#chart']}>
        <Routes>
          <Route path="/market" element={<MarketRedirect />} />
          <Route path="/p/market" element={<CurrentLocation />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('location').textContent).toBe(
      '/p/market?symbol=GSPC&tf=1D&returnTo=%2Fdashboard#chart',
    );
  });
});
