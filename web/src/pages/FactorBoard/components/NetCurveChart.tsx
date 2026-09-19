/**
 * Net-value curve for the two OOS backtest windows.
 *
 * Reads as the visual counterpart of the `decay` number right above it: the mining
 * window (2017→) and the out-of-sample window (2021→) on one timeline, both rebased
 * to their own first observation. If OOS flattens relative to mining, the factor
 * stopped working — which is exactly what `decay` quantifies.
 *
 * Two honesty notes that come from the data, not from taste:
 * - **Rebased, not raw.** The windows start at different absolute equity levels, so
 *   raw values on one axis would push one line into the floor. The panel says
 *   "growth" (`1.0× = starting equity`) rather than implying a shared baseline.
 * - **Gaps stay gaps.** A window that has no observation at an index is fed `null`
 *   so recharts breaks the line; interpolating across would invent data.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { NetCurvePoint } from '@/api/factors';

import { buildNetCurveData, formatGrowth } from '../utils/netCurve';

const CHART_HEIGHT = 180;

const MINING_COLOR = 'var(--color-text-secondary)';
const OOS_COLOR = 'var(--color-accent-primary)';

export function NetCurveChart({
  mining,
  oos,
}: {
  mining?: NetCurvePoint[] | null;
  oos?: NetCurvePoint[] | null;
}) {
  const { t } = useTranslation();
  const data = useMemo(() => buildNetCurveData(mining, oos), [mining, oos]);

  if (data.rows.length === 0) return null;

  // The x axis is the trading-day index; the tick label prefers the real date and
  // falls back to the index when the miner could not read a calendar.
  const axisLabel = (i: number, date: string | null) =>
    date ?? t('factors.oos.curve.dayIndex', { i });

  return (
    <figure className="factor-net-curve">
      <figcaption className="factor-net-curve__caption">
        <span className="factor-net-curve__legend">
          <span className="factor-net-curve__swatch" style={{ background: MINING_COLOR }} />
          {t('factors.oos.curve.mining')} {formatGrowth(data.miningEnd)}
        </span>
        <span className="factor-net-curve__legend">
          <span className="factor-net-curve__swatch" style={{ background: OOS_COLOR }} />
          {t('factors.oos.curve.oos')} {formatGrowth(data.oosEnd)}
        </span>
      </figcaption>

      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <LineChart data={data.rows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid stroke="var(--color-border-default)" vertical={false} />
          <XAxis
            dataKey="i"
            type="number"
            domain={['dataMin', 'dataMax']}
            tickFormatter={(i: number) => {
              const row = data.rows.find((r) => r.i === i);
              return axisLabel(i, row?.date ?? null);
            }}
            stroke="var(--color-text-tertiary)"
            fontSize={11}
            minTickGap={24}
          />
          <YAxis
            stroke="var(--color-text-tertiary)"
            fontSize={11}
            width={48}
            tickFormatter={(v: number) => `${v.toFixed(2)}×`}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--color-bg-popover)',
              border: '1px solid var(--color-border-default)',
              borderRadius: 'var(--radius)',
              fontSize: 12,
            }}
            // recharts types these callbacks loosely (label is ReactNode, value is
            // ValueType | undefined), so narrow explicitly instead of casting.
            labelFormatter={(label: unknown) => {
              const i = typeof label === 'number' ? label : Number(label);
              const row = data.rows.find((r) => r.i === i);
              return Number.isFinite(i) ? axisLabel(i, row?.date ?? null) : '';
            }}
            formatter={(value: unknown, name: unknown) => [
              formatGrowth(typeof value === 'number' ? value : null),
              t(name === 'mining' ? 'factors.oos.curve.mining' : 'factors.oos.curve.oos'),
            ]}
          />
          {/* connectNulls is OFF on purpose: a gap in one window must not be
              bridged by the other window's line. */}
          <Line
            type="monotone"
            dataKey="mining"
            stroke={MINING_COLOR}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="oos"
            stroke={OOS_COLOR}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>

      <p className="factor-card__note">{t('factors.oos.curve.note')}</p>
    </figure>
  );
}
