/**
 * Net-value curve geometry for the OOS panel — pure functions, no React/recharts.
 *
 * Why this layer exists rather than mapping inline: the two windows are not
 * directly comparable, and each way of "just plotting them" lies:
 *
 * - **Raw equity cannot share an axis.** The mining window starts at ~8.7e7 and
 *   the OOS window at a different absolute level; on one axis one curve is a flat
 *   line at the bottom. Both are therefore rebased to their **own first point**
 *   (growth = value / first), which is the only comparison that means anything:
 *   does the later window grow more slowly?
 * - **Date-only x-axis would truncate the mining window.** The two series start in
 *   different years; keying on the trading-day index `i` lets the OOS window sit
 *   *inside* the mining window's timeline instead of on a separate axis.
 * - **The index is the join key, not the array position.** A downsampled curve is
 *   evenly spaced but its first `i` is not guaranteed to be 0, so joining by array
 *   position would shift one window against the other.
 */

import type { NetCurvePoint } from '@/api/factors';

/** One merged row: both windows' rebased growth at trading-day index `i`. */
export interface NetCurveRow {
  i: number;
  date: string | null;
  /** Growth of the mining window (1 = its first observation). */
  mining: number | null;
  /** Growth of the OOS window; null outside the OOS range. */
  oos: number | null;
}

export interface NetCurveChartData {
  rows: NetCurveRow[];
  /** Rebased growth at the end of each window, null when that window is empty. */
  miningEnd: number | null;
  oosEnd: number | null;
  /** True when dates were available, so the x axis can be labelled by date. */
  hasDates: boolean;
}

/**
 * Rebase a curve to its first usable point.
 *
 * The base is the first **finite, non-zero** value, not blindly `curve[0].value`:
 * qlib's report starts with a placeholder `0` (the miner trims it, but a curve
 * that arrived with it must not turn into a column of `null`s — that renders as an
 * empty chart, indistinguishable from "this window failed").
 *
 * Entries before the base are `null`, and the returned array always matches the
 * input length so the caller's index-based join stays aligned. Returns `[]` only
 * for empty input; an all-zero / all-invalid curve yields length-matching nulls.
 */
export function rebaseCurve(curve: NetCurvePoint[] | null | undefined): Array<number | null> {
  if (!curve || curve.length === 0) return [];

  let base: number | null = null;
  for (const p of curve) {
    const v = p?.value;
    if (typeof v === 'number' && Number.isFinite(v) && v !== 0) {
      base = v;
      break;
    }
  }
  if (base === null) return curve.map(() => null);

  return curve.map((p) => {
    const v = p?.value;
    // v === 0 before the base is the placeholder; after it, a real flat point
    // would still divide to 0, which is a truthful growth value.
    return typeof v === 'number' && Number.isFinite(v) ? v / base : null;
  });
}

/**
 * Merge the two windows onto one index-keyed series.
 *
 * Rows are the union of both windows' indices, ascending. A window that has no
 * observation at an index yields `null` there (recharts breaks the line rather
 * than drawing straight through, which is what a gap should look like).
 */
export function buildNetCurveData(
  mining: NetCurvePoint[] | null | undefined,
  oos: NetCurvePoint[] | null | undefined,
): NetCurveChartData {
  const m = mining ?? [];
  const o = oos ?? [];
  if (m.length === 0 && o.length === 0) {
    return { rows: [], miningEnd: null, oosEnd: null, hasDates: false };
  }

  const mGrowth = rebaseCurve(m);
  const oGrowth = rebaseCurve(o);

  const byIndex = new Map<number, NetCurveRow>();
  const touch = (i: number, date: string | null): NetCurveRow => {
    let row = byIndex.get(i);
    if (!row) {
      row = { i, date, mining: null, oos: null };
      byIndex.set(i, row);
    } else if (row.date === null && date !== null) {
      // Prefer a real date: the OOS window may carry one where mining does not.
      row.date = date;
    }
    return row;
  };

  m.forEach((p, k) => {
    if (!p || typeof p.i !== 'number') return;
    touch(p.i, p.date ?? null).mining = mGrowth[k] ?? null;
  });
  o.forEach((p, k) => {
    if (!p || typeof p.i !== 'number') return;
    touch(p.i, p.date ?? null).oos = oGrowth[k] ?? null;
  });

  const rows = [...byIndex.values()].sort((a, b) => a.i - b.i);

  const lastFinite = (pick: (r: NetCurveRow) => number | null): number | null => {
    for (let k = rows.length - 1; k >= 0; k--) {
      const v = pick(rows[k]);
      if (v !== null && Number.isFinite(v)) return v;
    }
    return null;
  };

  return {
    rows,
    miningEnd: lastFinite((r) => r.mining),
    oosEnd: lastFinite((r) => r.oos),
    hasDates: rows.some((r) => r.date !== null),
  };
}

/**
 * Currency-free growth label, e.g. `1.42×`.
 *
 * Deliberately not a percentage: the reader's question is "how many times the
 * starting equity", and a growth of 1.42× is clearer than +42% when comparing
 * two windows that start at different absolute levels.
 */
export function formatGrowth(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  return `${value.toFixed(2)}×`;
}
