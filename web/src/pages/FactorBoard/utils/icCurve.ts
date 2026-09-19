/**
 * Factor decay-curve geometry — pure functions, no React/SVG/DOM.
 *
 * The board draws per-day IC as a small sparkline. Everything that can be wrong
 * in a way that is *invisible* on screen lives here, so it can be unit-tested:
 *
 *  - a degenerate y-domain (0 / Infinity / NaN) that turns the path into `NaN`
 *    and makes the browser drop the whole polyline;
 *  - a single-point series, which must render as a dot rather than an empty path;
 *  - `null` / non-finite ICs, which must be skipped without shifting the x-axis
 *    (otherwise every later point lands on the wrong day);
 *  - the sign convention: IC is signed and zero is meaningful, so the axis is
 *    symmetric around zero instead of expanded to the data's min/max.
 *
 * The x-axis is **index-based**, not date-based: bars are evenly spaced because
 * the miner's series only contains trading days it actually computed, so gaps
 * are missing observations rather than calendar distance.
 */

import type { IcPoint } from '@/api/factors';

export interface CurveConfig {
  width: number;
  height: number;
  padTop: number;
  padBottom: number;
  /** Absolute IC mapped to the top/bottom edge. */
  bound: number;
}

export interface CurvePoint {
  x: number;
  y: number;
  /** Zero line for this chart, for reference/extents. */
  zeroY: number;
  ic: number;
}

export interface IcCurve {
  points: CurvePoint[];
  /** SVG `d` for a polyline, or '' when there is nothing to draw. */
  path: string;
  /** True when there is exactly one usable point (draw a dot, not a line). */
  single: boolean;
  /** Strongest |IC| in this series, null when empty. */
  peak: { date: string; ic: number } | null;
  /** Mean cross-section size across usable points, null when unknown. */
  meanN: number | null;
}

/**
 * A date label that cannot be shifted by the viewer's timezone.
 *
 * The year-month-day is parsed out of the ISO string and rebuilt in UTC, then
 * formatted in the viewer's locale. Going through `new Date("2025-01-02")` and a
 * local formatter would show the previous day for any viewer west of UTC.
 *
 * `locale` exists so tests can pin the language instead of depending on whatever
 * the CI machine is set to; callers normally leave it undefined (browser locale).
 */
export function formatIcDate(date: string, locale?: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!m) return date;
  const [, y, mo, d] = m;
  return new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d))).toLocaleDateString(
    locale,
    { month: 'short', day: 'numeric', timeZone: 'UTC' },
  );
}

/**
 * Round a magnitude up to a readable bound, so the axis label is a round number
 * instead of the data's arbitrary extreme.
 *
 * Steps are steep on purpose: IC values cluster near zero, and a linear headroom
 * rule would produce labels like `0.0431`. The returned bound is always > 0 so a
 * flat-zero series (or an all-NaN one) can't produce a zero-height domain.
 */
export function niceIcBound(rawMaxAbs: number): number {
  if (!Number.isFinite(rawMaxAbs) || rawMaxAbs <= 0) return 0.01;
  const steps = [0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5, 1];
  for (const s of steps) {
    if (rawMaxAbs <= s) return s;
  }
  return Math.ceil(rawMaxAbs * 10) / 10;
}

/**
 * Largest |IC| across every series, ignoring non-finite values.
 * Returns 0 for empty/undefined input so `niceIcBound` can apply its floor.
 */
export function maxAbsIc(seriesList: Array<IcPoint[] | undefined>): number {
  let max = 0;
  for (const series of seriesList) {
    if (!series) continue;
    for (const p of series) {
      const v = p?.ic;
      if (typeof v === 'number' && Number.isFinite(v)) {
        max = Math.max(max, Math.abs(v));
      }
    }
  }
  return max;
}

/**
 * Build the drawable geometry for one IC series.
 *
 * Points with a missing/non-finite IC are dropped, and x is assigned from the
 * **compacted** index — a dropped day must not leave a hole that shifts every
 * later point.
 */
export function buildIcCurve(series: IcPoint[] | undefined, cfg: CurveConfig): IcCurve {
  const empty: IcCurve = { points: [], path: '', single: false, peak: null, meanN: null };
  if (!series || series.length === 0) return empty;

  const { width, height, padTop, padBottom, bound } = cfg;
  const usable = series.filter(
    (p): p is IcPoint => !!p && typeof p.ic === 'number' && Number.isFinite(p.ic),
  );
  if (usable.length === 0) return empty;

  const plotW = width;
  const plotH = height - padTop - padBottom;
  if (!(plotW > 0) || !(plotH > 0)) return empty;

  const safeBound = Number.isFinite(bound) && bound > 0 ? bound : 0.01;
  const zeroY = padTop + plotH / 2;
  const scaleY = (ic: number) => {
    const v = zeroY - (ic / safeBound) * (plotH / 2);
    // Clamp so a value beyond the axis can never draw outside the box.
    return Math.min(Math.max(v, padTop), padTop + plotH);
  };

  const n = usable.length;
  const points: CurvePoint[] = usable.map((p, i) => ({
    x: n === 1 ? width / 2 : (i / (n - 1)) * plotW,
    y: scaleY(p.ic),
    zeroY,
    ic: p.ic,
  }));

  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ');

  let peak: { date: string; ic: number } | null = null;
  const withN: number[] = [];
  for (const p of usable) {
    if (!peak || Math.abs(p.ic) > Math.abs(peak.ic)) peak = { date: p.date, ic: p.ic };
    if (typeof p.n === 'number' && Number.isFinite(p.n)) withN.push(p.n);
  }

  return {
    points,
    path,
    single: n === 1,
    peak,
    meanN: withN.length > 0 ? withN.reduce((a, b) => a + b, 0) / withN.length : null,
  };
}

/** The `weak`/`strong` reading of IC — must match the backend verdict thresholds. */
export const IC_WEAK = 0.02;
export const IC_STRONG = 0.05;

/** The zero baseline as a drawable segment (kept separate — it has no data). */
export function zeroLine(cfg: CurveConfig): { y: number; path: string } {
  const plotH = cfg.height - cfg.padTop - cfg.padBottom;
  const y = cfg.padTop + plotH / 2;
  return { y, path: `M0 ${y.toFixed(2)} L${cfg.width.toFixed(2)} ${y.toFixed(2)}` };
}
