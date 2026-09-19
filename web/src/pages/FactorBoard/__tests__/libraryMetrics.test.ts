/**
 * The chart transform, pinned.
 *
 * These assertions are about the two ways a factor chart can lie: reordering the
 * periods (so "1d, 10d, 5d" reads as a trend) and turning a `null` the miner could
 * not measure into a zero the chart draws. Everything else here is shape plumbing.
 */
import { describe, expect, it } from 'vitest';

import type { TearSheet } from '@/api/factors';
import {
  icDecaySeries,
  icSummary,
  longShortSeries,
  monotonicityFor,
  periodDays,
  periodsOf,
  quantileBars,
  shortestPeriod,
  turnoverBars,
} from '../utils/libraryMetrics';

const TEARSHEET: TearSheet = {
  quantile_returns: {
    '10d': { mean_period_return: { q1: -0.01, q2: 0.0, q3: 0.004, q4: 0.006, q5: 0.009 } },
    '1d': { mean_period_return: { q1: -0.002, q2: -0.0005, q3: null, q4: 0.001, q5: 0.002 } },
    '5d': { mean_period_return: { q1: -0.005, q2: 0.001, q3: 0.002, q4: 0.003, q5: 0.005 } },
  },
  long_short: {
    '1d': { mean_period_spread: 0.004, annualized: 1.0 },
    '10d': { mean_period_spread: 0.019, annualized: 0.48 },
    '5d': { mean_period_spread: 0.01, annualized: 0.5 },
  },
  ic: {
    period: '1d',
    mean: 0.0404,
    std: 0.196,
    ir: 0.206,
    series_summary: { days: 466, positive_ratio: 0.5686 },
    decay: { '10d': 0.0927, '1d': 0.0404, '5d': 0.0722 },
  },
  turnover: { top: 0.184, bottom: 0.181 },
};

describe('periods', () => {
  it('sorts numerically, not lexically', () => {
    expect(periodsOf(TEARSHEET)).toEqual(['1d', '5d', '10d']);
    expect(periodDays('10d')).toBe(10);
    expect(periodDays('nonsense')).toBeGreaterThan(1000);
  });

  it('defaults to the shortest period, which is the tradeable one', () => {
    expect(shortestPeriod(periodsOf(TEARSHEET))).toBe('1d');
    expect(shortestPeriod([])).toBeNull();
  });

  it('returns nothing for a tearsheet that has no periods', () => {
    expect(periodsOf(undefined)).toEqual([]);
    expect(periodsOf({})).toEqual([]);
  });
});

describe('quantile bars', () => {
  it('keeps Q1..Q5 in bucket order', () => {
    const bars = quantileBars(TEARSHEET, '1d');
    expect(bars.map((bar) => bar.label)).toEqual(['Q1', 'Q2', 'Q3', 'Q4', 'Q5']);
  });

  it('passes an unmeasured bucket through as null, never as 0', () => {
    const bars = quantileBars(TEARSHEET, '1d');
    expect(bars[2]).toEqual({ label: 'Q3', value: null });
    // A null must stay distinguishable from a measured zero.
    expect(quantileBars(TEARSHEET, '10d')[1]).toEqual({ label: 'Q2', value: 0 });
  });

  it('has no bars without a period', () => {
    expect(quantileBars(TEARSHEET, null)).toEqual([]);
  });
});

describe('decay and spread series', () => {
  it('orders IC decay by holding period', () => {
    expect(icDecaySeries(TEARSHEET).map((point) => point.period)).toEqual(['1d', '5d', '10d']);
    expect(icDecaySeries(TEARSHEET)[2].value).toBeCloseTo(0.0927);
  });

  it('orders the long-short spread the same way', () => {
    const spreads = longShortSeries(TEARSHEET);
    expect(spreads.map((point) => point.period)).toEqual(['1d', '5d', '10d']);
    expect(spreads[1].value).toBeCloseTo(0.01);
  });

  it('is empty rather than wrong when the block is missing', () => {
    expect(icDecaySeries({})).toEqual([]);
    expect(longShortSeries({})).toEqual([]);
  });
});

describe('turnover and IC summary', () => {
  it('reports top and bottom buckets, gaps included', () => {
    expect(turnoverBars(TEARSHEET)).toEqual([
      { label: 'top', value: 0.184 },
      { label: 'bottom', value: 0.181 },
    ]);
    expect(turnoverBars({}).map((bar) => bar.value)).toEqual([null, null]);
  });

  it('carries the t-stat and half-life the miner computed', () => {
    expect(icSummary(TEARSHEET.ic, 3.52, 4.5)).toEqual({
      mean: 0.0404,
      ir: 0.206,
      tStat: 3.52,
      days: 466,
      positiveRatio: 0.5686,
      halfLifeDays: 4.5,
    });
  });

  it('leaves the half-life null when IC does not decay', () => {
    // Rising IC (0.0404 → 0.0927) is a strengthening factor: the miner reports no
    // half-life, and the panel must say so rather than draw a decay that rises.
    expect(icSummary(TEARSHEET.ic, 3.52, null).halfLifeDays).toBeNull();
  });
});

describe('monotonicity', () => {
  const monotonicity = {
    '1d': { rho: 0.3, direction: 'non_monotonic' as const, monotonic: false },
    '5d': { rho: 0.7, direction: 'non_monotonic' as const, monotonic: false },
  };

  it('picks the verdict for the period on screen', () => {
    expect(monotonicityFor(monotonicity, '5d')?.rho).toBe(0.7);
  });

  it('is explicit about "no verdict" instead of assuming monotone', () => {
    expect(monotonicityFor(monotonicity, '10d')).toBeNull();
    expect(monotonicityFor(undefined, '1d')).toBeNull();
    expect(monotonicityFor(monotonicity, null)).toBeNull();
  });
});
