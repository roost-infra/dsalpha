/**
 * Indicator algorithm layer — pure functions, no chart/DOM/React dependency.
 *
 * Rationale: these used to grow inline inside the 2400-line MarketChart.tsx (or as
 * untested helpers next to it). Keeping them pure means they can be unit-tested with
 * plain arrays and reused by the factor board / backtest views later.
 *
 * Conventions (same as chan.ts):
 *  - never return NaN / Infinity; drop or null the offending point instead;
 *  - return `null` for the warm-up region of line-style series so the renderer can
 *    skip it without drawing a fake zero;
 *  - aligned series are returned as a full-length array parallel to the input
 *    (index i corresponds to bar i), which makes overlay rendering trivial.
 */

export interface Bar {
  time: number;
  open?: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

/** A point on a line-style indicator; `value: null` marks warm-up / missing data. */
export interface LinePoint {
  time: number;
  value: number | null;
}

function isValid(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/**
 * Exponential Moving Average.
 * Seeded with the SMA of the first `period` values (the conventional TradingView
 * behaviour), then EMA_t = close_t * k + EMA_{t-1} * (1 - k), k = 2/(period+1).
 * Warm-up entries are `null`.
 */
export function calculateEMA(bars: Bar[], period: number): LinePoint[] {
  if (period <= 0 || bars.length === 0) return [];
  const out: LinePoint[] = bars.map((b) => ({ time: b.time, value: null }));
  if (bars.length < period) return out;

  const k = 2 / (period + 1);
  let sum = 0;
  for (let i = 0; i < period; i++) sum += bars[i].close;
  let ema = sum / period;
  out[period - 1] = { time: bars[period - 1].time, value: ema };

  for (let i = period; i < bars.length; i++) {
    ema = bars[i].close * k + ema * (1 - k);
    if (isValid(ema)) out[i] = { time: bars[i].time, value: ema };
  }
  return out;
}

/**
 * Simple Moving Average over `source` (default close).
 * Unlike calculateMA in chartHelpers this keeps the full-length alignment, returning
 * `null` during warm-up. Callers that need the compact old shape use calculateMA.
 */
export function calculateSMA(
  bars: Bar[],
  period: number,
  source: (b: Bar) => number = (b) => b.close,
): LinePoint[] {
  // Contract, shared with calculateEMA/calculateATR/calculateMACD:
  // illegal period → [] ; insufficient data → aligned all-null sequence.
  if (period <= 0) return [];
  const out: LinePoint[] = bars.map((b) => ({ time: b.time, value: null }));
  if (bars.length < period) return out;

  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += source(bars[i]);
    if (i >= period) sum -= source(bars[i - period]);
    if (i >= period - 1) {
      const v = sum / period;
      if (isValid(v)) out[i] = { time: bars[i].time, value: v };
    }
  }
  return out;
}

export interface BollingerBands {
  upper: LinePoint[];
  middle: LinePoint[];
  lower: LinePoint[];
  period: number;
  stdDev: number;
}

/**
 * Bollinger Bands with a *population* standard deviation (divide by n), which is what
 * TradingView and most charting packages use for BB — not the sample (n-1) estimator.
 */
export function calculateBollinger(
  bars: Bar[],
  period: number = 20,
  stdDevMultiplier: number = 2,
): BollingerBands {
  const upper: LinePoint[] = bars.map((b) => ({ time: b.time, value: null }));
  const middle: LinePoint[] = bars.map((b) => ({ time: b.time, value: null }));
  const lower: LinePoint[] = bars.map((b) => ({ time: b.time, value: null }));
  const result: BollingerBands = { upper, middle, lower, period, stdDev: stdDevMultiplier };
  if (period <= 0 || bars.length < period) return result;

  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < bars.length; i++) {
    const c = bars[i].close;
    sum += c;
    sumSq += c * c;
    if (i >= period) {
      const old = bars[i - period].close;
      sum -= old;
      sumSq -= old * old;
    }
    if (i < period - 1) continue;

    const mean = sum / period;
    // Clamp at 0: catastrophic cancellation can make this a tiny negative number
    // when prices are large and tightly clustered.
    const variance = Math.max(0, sumSq / period - mean * mean);
    const sd = Math.sqrt(variance);
    const t = bars[i].time;
    if (isValid(mean) && isValid(sd)) {
      middle[i] = { time: t, value: mean };
      upper[i] = { time: t, value: mean + stdDevMultiplier * sd };
      lower[i] = { time: t, value: mean - stdDevMultiplier * sd };
    }
  }
  return result;
}

export interface MACDResult {
  macd: LinePoint[];
  signal: LinePoint[];
  /** Histogram = macd - signal. */
  histogram: LinePoint[];
  fastPeriod: number;
  slowPeriod: number;
  signalPeriod: number;
}

/** Internal EMA that carries a value forward without the null-padded public shape. */
function emaValues(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = values.map(() => null);
  if (period <= 0 || values.length < period) return out;
  const k = 2 / (period + 1);
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  let ema = sum / period;
  out[period - 1] = ema;
  for (let i = period; i < values.length; i++) {
    ema = values[i] * k + ema * (1 - k);
    out[i] = ema;
  }
  return out;
}

/**
 * MACD (12, 26, 9 by default).
 *
 * The signal line is an EMA *of the MACD line*, so it only starts once there are
 * `signalPeriod` valid MACD values — i.e. the first signal point lands at index
 * slowPeriod - 1 + signalPeriod - 1. Warm-up entries stay null.
 */
export function calculateMACD(
  bars: Bar[],
  fastPeriod: number = 12,
  slowPeriod: number = 26,
  signalPeriod: number = 9,
): MACDResult {
  const macd: LinePoint[] = bars.map((b) => ({ time: b.time, value: null }));
  const signal: LinePoint[] = bars.map((b) => ({ time: b.time, value: null }));
  const histogram: LinePoint[] = bars.map((b) => ({ time: b.time, value: null }));
  const result: MACDResult = { macd, signal, histogram, fastPeriod, slowPeriod, signalPeriod };
  if (bars.length === 0 || fastPeriod <= 0 || slowPeriod <= 0 || signalPeriod <= 0) return result;

  const closes = bars.map((b) => b.close);
  const fast = emaValues(closes, fastPeriod);
  const slow = emaValues(closes, slowPeriod);

  const macdRaw: (number | null)[] = closes.map((_, i) => {
    const f = fast[i];
    const s = slow[i];
    if (!isValid(f) || !isValid(s)) return null;
    return f - s;
  });

  // Signal = EMA over the compact run of valid MACD values, then mapped back to bar
  // indices so everything stays aligned with the input array.
  const validIdx: number[] = [];
  const validVals: number[] = [];
  macdRaw.forEach((v, i) => {
    if (isValid(v)) {
      validIdx.push(i);
      validVals.push(v);
    }
  });
  const signalOnValid = emaValues(validVals, signalPeriod);

  validIdx.forEach((barIdx, j) => {
    const mv = macdRaw[barIdx];
    if (isValid(mv)) macd[barIdx] = { time: bars[barIdx].time, value: mv };
    const sv = signalOnValid[j];
    if (isValid(sv)) {
      signal[barIdx] = { time: bars[barIdx].time, value: sv };
      if (isValid(mv)) {
        histogram[barIdx] = { time: bars[barIdx].time, value: mv - sv };
      }
    }
  });

  return result;
}

/**
 * Wilder's Average True Range with Wilder smoothing (the original ATR).
 * True Range of bar i = max(high-low, |high-prevClose|, |low-prevClose|);
 * the first bar contributes plain high-low.
 * ATR is seeded with the SMA of the first `period` true ranges, then
 * ATR_t = (ATR_{t-1} * (period-1) + TR_t) / period.
 */
export function calculateATR(bars: Bar[], period: number = 14): LinePoint[] {
  // Contract, shared with calculateEMA/calculateSMA/calculateMACD.
  if (period <= 0) return [];
  const out: LinePoint[] = bars.map((b) => ({ time: b.time, value: null }));
  if (bars.length < period) return out;

  const trueRange = (i: number): number => {
    const b = bars[i];
    if (i === 0) return b.high - b.low;
    const prevClose = bars[i - 1].close;
    return Math.max(
      b.high - b.low,
      Math.abs(b.high - prevClose),
      Math.abs(b.low - prevClose),
    );
  };

  let sum = 0;
  for (let i = 0; i < period; i++) sum += trueRange(i);
  let atr = sum / period;
  out[period - 1] = { time: bars[period - 1].time, value: atr };

  for (let i = period; i < bars.length; i++) {
    atr = (atr * (period - 1) + trueRange(i)) / period;
    if (isValid(atr)) out[i] = { time: bars[i].time, value: atr };
  }
  return out;
}

/** Most recent non-null value of an aligned series, or null. */
export function lastValid(points: LinePoint[]): number | null {
  for (let i = points.length - 1; i >= 0; i--) {
    const v = points[i]?.value;
    if (isValid(v)) return v;
  }
  return null;
}

export interface RiskLevel {
  /** Risk multiple, e.g. 1 for 1R. */
  r: number;
  price: number;
  side: "long" | "short";
}

export interface RiskProjection {
  entry: number;
  stop: number;
  /** Absolute risk per unit: |entry - stop|. */
  risk: number;
  side: "long" | "short";
  levels: RiskLevel[];
  /** Price at -1R (i.e. the stop itself), included for drawing symmetry. */
  stopR: RiskLevel;
}

/**
 * R-multiple projection from an entry and a stop.
 *
 * This is the piece that makes ATR actionable rather than decorative: a trade plan is
 * "risk 1 ATR below entry, take 2R/3R", and the chart can then draw entry / stop /
 * target lines that actually correspond to the stop distance the user chose.
 *
 * Invariant: the stop must sit on the losing side of the entry — below it for a long,
 * above it for a short. `side` is normally inferred from that position. An explicit
 * `side` that contradicts it (e.g. side='short' with stop < entry) is a caller bug,
 * and silently normalising it would put the targets on the stop's side of the entry,
 * so this returns null instead.
 */
export function projectRiskLevels(
  entry: number,
  stop: number,
  multiples: number[] = [1, 2, 3],
  side?: "long" | "short",
): RiskProjection | null {
  if (!isValid(entry) || !isValid(stop) || entry === stop) return null;

  const inferred: "long" | "short" = stop < entry ? "long" : "short";
  if (side !== undefined && side !== inferred) return null;

  const resolved = inferred;
  const risk = Math.abs(entry - stop);
  // Targets always move away from the stop: up for a long, down for a short.
  const dir = resolved === "long" ? 1 : -1;

  const levels: RiskLevel[] = multiples
    .filter((m) => isValid(m) && m > 0)
    .map((m) => ({ r: m, price: entry + dir * risk * m, side: resolved }));

  return {
    entry,
    stop,
    risk,
    side: resolved,
    levels,
    stopR: { r: -1, price: stop, side: resolved },
  };
}

/**
 * Position size implied by risking a fixed fraction of equity over a given risk
 * (usually 1 ATR). Returns null when the risk distance is not usable.
 */
export function riskPositionSize(
  equity: number,
  riskFraction: number,
  riskPerUnit: number,
): number | null {
  if (!isValid(equity) || !isValid(riskFraction) || !isValid(riskPerUnit)) return null;
  if (equity <= 0 || riskFraction <= 0 || riskPerUnit <= 0) return null;
  return (equity * riskFraction) / riskPerUnit;
}
