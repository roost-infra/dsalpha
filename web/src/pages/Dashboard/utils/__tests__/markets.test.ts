import { describe, it, expect } from 'vitest';
import {
  DASHBOARD_MARKETS,
  DEFAULT_DASHBOARD_MARKET,
  MARKET_INDEX_CATALOG,
  isCnSymbol,
  isDashboardMarket,
  marketBlueChips,
  marketIndexName,
  marketIndexSymbols,
  marketOfSymbol,
  venueTimeZoneForSymbol,
} from '../markets';

describe('dashboard markets', () => {
  it('ships a five-tile index row for each region', () => {
    // A-shares lead the switch: the product's default reader is A-share first.
    expect(DASHBOARD_MARKETS).toEqual(['cn', 'us']);
    expect(DEFAULT_DASHBOARD_MARKET).toBe('cn');
    for (const market of DASHBOARD_MARKETS) {
      expect(MARKET_INDEX_CATALOG[market]).toHaveLength(5);
      expect(marketIndexSymbols(market)).toHaveLength(5);
    }
  });

  it('spells CN indices with a venue suffix and US ones without', () => {
    // A bare 000001 is Ping An Bank (SZSE); the Shanghai Composite needs .SH.
    expect(marketIndexSymbols('cn')).toEqual(
      expect.arrayContaining(['000001.SH', '399001.SZ', '000300.SH']),
    );
    for (const code of marketIndexSymbols('cn')) expect(isCnSymbol(code)).toBe(true);
    for (const code of marketIndexSymbols('us')) expect(isCnSymbol(code)).toBe(false);
  });

  it('only accepts the two shipped regions', () => {
    expect(isDashboardMarket('us')).toBe(true);
    expect(isDashboardMarket('cn')).toBe(true);
    expect(isDashboardMarket('jp')).toBe(false);
    expect(isDashboardMarket(undefined)).toBe(false);
  });

  it('localizes a catalog index and leaves an unknown symbol to the caller', () => {
    expect(marketIndexName('000001.SH', 'zh-CN')).toBe('上证指数');
    expect(marketIndexName('000001.SH', 'en-US')).toBe('SSE Composite');
    expect(marketIndexName('600519.SH', 'zh-CN')).toBeUndefined();
  });

  it('seeds a fresh card with that region’s listings', () => {
    expect(marketBlueChips('us')).toContain('NVDA');
    expect(marketBlueChips('cn')).toContain('600519.SH');
    for (const symbol of marketBlueChips('cn')) expect(isCnSymbol(symbol)).toBe(true);
    // Fresh arrays: a caller sorting the seed must not mutate the catalog.
    const first = marketBlueChips('cn');
    first.pop();
    expect(marketBlueChips('cn')).toHaveLength(6);
  });

  it('reads the venue off the symbol', () => {
    expect(marketOfSymbol('600519.SH')).toBe('cn');
    expect(marketOfSymbol('000001.SZ')).toBe('cn');
    expect(marketOfSymbol('899050.BJ')).toBe('cn');
    expect(marketOfSymbol('NVDA')).toBe('us');
    expect(marketOfSymbol('AAPL.US')).toBe('us');
    expect(venueTimeZoneForSymbol('600519.SH')).toBe('Asia/Shanghai');
    expect(venueTimeZoneForSymbol('NVDA')).toBe('America/New_York');
  });
});
