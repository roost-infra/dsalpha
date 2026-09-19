/**
 * Turning a stored tearsheet into the four chart series the detail panel draws.
 *
 * This is a pure transform on purpose. The tearsheet arrives from another service
 * as a nested, stringly-keyed object ("1d", "5d", "10d"), and every chart needs
 * the same three things done to it — sort the periods, pick one out, and keep
 * `null` as a gap rather than as a zero. Spreading that across four components
 * would mean four chances to render a missing number as a real one, which is the
 * one mistake a factor chart must not make.
 */

import type {
  IcStats,
  MonotonicityReport,
  TearSheet,
} from '@/api/factors';

export interface NamedValue {
  label: string;
  /** `null` = not measured. Charts must break the line / skip the bar. */
  value: number | null;
}

export interface PeriodSeries {
  period: string;
  days: number;
  value: number | null;
}

/** "10d" → 10. Unparseable keys sort last rather than throwing mid-render. */
export function periodDays(period: string): number {
  const days = Number.parseInt(String(period).replace(/[^0-9]/g, ''), 10);
  return Number.isFinite(days) ? days : Number.MAX_SAFE_INTEGER;
}

/** The forward periods present in the tearsheet, ascending (1d, 5d, 10d). */
export function periodsOf(tearsheet: TearSheet | undefined): string[] {
  const keys = new Set<string>([
    ...Object.keys(tearsheet?.quantile_returns ?? {}),
    ...Object.keys(tearsheet?.long_short ?? {}),
    ...Object.keys(tearsheet?.ic?.decay ?? {}),
  ]);
  return [...keys].sort((a, b) => periodDays(a) - periodDays(b));
}

/** The default period a chart shows: the shortest one, which is the tradeable one. */
export function shortestPeriod(periods: string[]): string | null {
  return periods.length ? periods[0] : null;
}

/** Q1..Qn mean returns for one period — the monotonicity evidence, as bars. */
export function quantileBars(tearsheet: TearSheet | undefined, period: string | null): NamedValue[] {
  if (!period) return [];
  const means = tearsheet?.quantile_returns?.[period]?.mean_period_return ?? {};
  return Object.keys(means)
    .sort((a, b) => periodDays(a.replace('q', '')) - periodDays(b.replace('q', '')))
    .map((label) => ({ label: label.toUpperCase(), value: asNumber(means[label]) }));
}

/** Mean IC per forward period. Rising IC is not a decay, and it must not read as one. */
export function icDecaySeries(tearsheet: TearSheet | undefined): PeriodSeries[] {
  const decay = tearsheet?.ic?.decay ?? {};
  return Object.keys(decay)
    .sort((a, b) => periodDays(a) - periodDays(b))
    .map((period) => ({ period, days: periodDays(period), value: asNumber(decay[period]) }));
}

/** Long-short spread (top quantile minus bottom) per forward period. */
export function longShortSeries(tearsheet: TearSheet | undefined): PeriodSeries[] {
  const spreads = tearsheet?.long_short ?? {};
  return Object.keys(spreads)
    .sort((a, b) => periodDays(a) - periodDays(b))
    .map((period) => ({
      period,
      days: periodDays(period),
      value: asNumber(spreads[period]?.mean_period_spread),
    }));
}

/** Top/bottom quantile turnover — the holding-cost side of the factor. */
export function turnoverBars(tearsheet: TearSheet | undefined): NamedValue[] {
  const turnover = tearsheet?.turnover ?? {};
  return (['top', 'bottom'] as const).map((side) => ({
    label: side,
    value: asNumber(turnover[side]),
  }));
}

/** IC statistics for the headline strip, with the t-stat the miner computed. */
export interface IcSummary {
  mean: number | null;
  ir: number | null;
  tStat: number | null;
  days: number | null;
  positiveRatio: number | null;
  halfLifeDays: number | null;
}

export function icSummary(
  ic: IcStats | undefined,
  tStat: number | null | undefined,
  halfLifeDays: number | null | undefined,
): IcSummary {
  return {
    mean: asNumber(ic?.mean),
    ir: asNumber(ic?.ir),
    tStat: asNumber(tStat),
    days: typeof ic?.series_summary?.days === 'number' ? ic.series_summary.days : null,
    positiveRatio: asNumber(ic?.series_summary?.positive_ratio),
    halfLifeDays: asNumber(halfLifeDays),
  };
}

/**
 * The monotonicity verdict for one period.
 *
 * `rho` is strength, `monotonic` is the strict verdict, and a factor that is
 * "almost" monotone must not be shown as monotone — the miner is explicit about
 * that distinction and this only carries it to the surface.
 */
export function monotonicityFor(
  monotonicity: Record<string, MonotonicityReport> | undefined,
  period: string | null,
): MonotonicityReport | null {
  if (!period) return null;
  return monotonicity?.[period] ?? null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return null;
}
