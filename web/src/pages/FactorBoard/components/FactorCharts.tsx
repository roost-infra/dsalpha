/**
 * The four professional charts for one factor: quantile returns, IC decay,
 * long-short spread and turnover — the alphalens-shaped read of a tearsheet.
 *
 * Three decisions are worth stating, because each is a way this panel could lie:
 *
 * - **A missing number is a gap, not a zero.** The miner returns `null` for a
 *   period it could not measure, and a chart that drew it at 0 would invent a
 *   dead factor. Recharts is fed `null` and breaks the line / skips the bar.
 * - **Monotonicity is shown as a verdict, not as a shape.** The eye reads five
 *   rising bars as "monotone" even when the last one dips; the badge says what
 *   the miner decided (strict, per period) and carries `rho` as the strength.
 * - **Rising IC is labelled as rising.** A factor whose IC grows with the holding
 *   period has no half-life; the panel says so instead of drawing a "decay" curve
 *   that only goes up.
 *
 * Colors come from the token layer as `var(...)` strings — the same contract the
 * dashboard sparkline uses, so both themes are styled by construction.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { FactorLibraryItem } from '@/api/factors';
import { useLocale } from '@/hooks/useLocale';
import { createFormatter } from '@/lib/format';
import {
  icDecaySeries,
  icSummary,
  longShortSeries,
  monotonicityFor,
  periodsOf,
  quantileBars,
  shortestPeriod,
  turnoverBars,
  type NamedValue,
} from '../utils/libraryMetrics';

// Returns and turnover are fractions of one; IC is a correlation and stays a
// plain number. Four decimals is the resolution the miner itself reports.
const pct2 = createFormatter({ style: 'percent', maximumFractionDigits: 2 });
const pct1 = createFormatter({ style: 'percent', maximumFractionDigits: 1 });
const corr = createFormatter({ minimumFractionDigits: 3, maximumFractionDigits: 4 });
const plain1 = createFormatter({ maximumFractionDigits: 1 });

const CHART_HEIGHT = 168;

/** Bars coloured by sign, because a negative quantile mean is the whole point. */
function signColor(value: number | null): string {
  if (value === null) return 'var(--color-border-default)';
  if (value > 0) return 'var(--color-profit)';
  if (value < 0) return 'var(--color-loss)';
  return 'var(--color-text-secondary)';
}

function ChartFrame({
  title,
  note,
  badge,
  children,
}: {
  title: string;
  note?: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <figure className="factor-chart">
      <figcaption className="factor-chart__caption">
        <span className="factor-chart__title">{title}</span>
        {badge}
      </figcaption>
      <div className="factor-chart__plot" style={{ height: CHART_HEIGHT }}>
        {children}
      </div>
      {note && <p className="factor-chart__note">{note}</p>}
    </figure>
  );
}

function EmptyPlot({ label }: { label: string }) {
  return (
    <div className="factor-chart__empty">
      <span>{label}</span>
    </div>
  );
}

function AxisTick({ x, y, payload }: { x?: number; y?: number; payload?: { value?: string } }) {
  return (
    <text
      x={x}
      y={y}
      dy={4}
      textAnchor="middle"
      fontSize={11}
      fill="var(--color-text-secondary)"
    >
      {payload?.value ?? ''}
    </text>
  );
}

export function FactorCharts({ item, period }: { item: FactorLibraryItem; period: string | null }) {
  const { t } = useTranslation();
  // createFormatter is locale-parameterised now: the formatter objects are
  // module-level (one Intl cache per option set), the locale comes from render.
  const locale = useLocale();
  const tearsheet = item.metrics?.tearsheet;

  const periods = useMemo(() => periodsOf(tearsheet), [tearsheet]);
  const activePeriod = period && periods.includes(period) ? period : shortestPeriod(periods);

  const quantiles = useMemo(() => quantileBars(tearsheet, activePeriod), [tearsheet, activePeriod]);
  const decay = useMemo(() => icDecaySeries(tearsheet), [tearsheet]);
  const spreads = useMemo(
    () =>
      longShortSeries(tearsheet).map((point) => ({
        period: point.period,
        spread: point.value,
      })),
    [tearsheet],
  );
  const turnover = useMemo(() => turnoverBars(tearsheet), [tearsheet]);
  const stats = useMemo(
    () => icSummary(tearsheet?.ic, item.t_stat, item.ic_half_life_days),
    [tearsheet, item.t_stat, item.ic_half_life_days],
  );
  const monotonicity = monotonicityFor(item.monotonicity, activePeriod);

  if (!tearsheet || !periods.length) {
    return <EmptyPlot label={t('factors.library.charts.none')} />;
  }

  const decayRising =
    decay.length > 1 &&
    decay.every((point) => point.value !== null) &&
    (decay[decay.length - 1].value as number) > (decay[0].value as number);

  return (
    <div className="factor-charts">
      <ChartFrame
        title={t('factors.library.charts.quantiles', { period: activePeriod ?? '' })}
        badge={
          monotonicity ? (
            <span
              className={`factor-chart__badge factor-chart__badge--${
                monotonicity.monotonic ? 'ok' : 'flat'
              }`}
            >
              {monotonicity.monotonic
                ? t('factors.library.monotonic.yes', {
                    direction:
                      monotonicity.direction === 'decreasing'
                        ? t('factors.library.monotonic.down')
                        : t('factors.library.monotonic.up'),
                  })
                : t('factors.library.monotonic.no', {
                    rho: monotonicity.rho === null || monotonicity.rho === undefined
                      ? '—'
                      : plain1(monotonicity.rho, locale),
                  })}
            </span>
          ) : null
        }
        note={t('factors.library.charts.quantilesNote')}
      >
        {quantiles.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={quantiles} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="var(--color-border-muted)" vertical={false} />
              <XAxis dataKey="label" tick={<AxisTick />} axisLine={false} tickLine={false} />
              <YAxis hide domain={['auto', 'auto']} />
              <ReferenceLine y={0} stroke="var(--color-border-default)" />
              <Tooltip
                cursor={{ fill: 'var(--color-bg-hover)' }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const point = payload[0].payload as NamedValue;
                  return (
                    <div className="factor-tooltip">
                      <div className="factor-tooltip__label">{point.label}</div>
                      <div className="factor-tooltip__value">
                        {point.value === null ? t('factors.library.notMeasured') : pct2(point.value, locale)}
                      </div>
                    </div>
                  );
                }}
              />
              <Bar dataKey="value" isAnimationActive={false} radius={[2, 2, 0, 0]}>
                {quantiles.map((point) => (
                  <Cell key={point.label} fill={signColor(point.value)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <EmptyPlot label={t('factors.library.notMeasured')} />
        )}
      </ChartFrame>

      <ChartFrame
        title={t('factors.library.charts.ic')}
        note={decayRising ? t('factors.library.charts.icRising') : t('factors.library.charts.icNote')}
      >
        <div className="factor-chart__stats">
          <Stat label="IC" value={stats.mean === null ? '—' : corr(stats.mean, locale)} />
          <Stat label="IR" value={stats.ir === null ? '—' : corr(stats.ir, locale)} />
          <Stat label="t" value={stats.tStat === null ? '—' : plain1(stats.tStat, locale)} />
          <Stat
            label={t('factors.library.detail.samples')}
            value={stats.days === null ? '—' : String(stats.days)}
          />
          <Stat
            label={t('factors.library.detail.halfLife')}
            value={
              stats.halfLifeDays === null
                ? t('factors.library.detail.halfLifeNone')
                : t('factors.library.detail.days', { value: plain1(stats.halfLifeDays, locale) })
            }
          />
        </div>
        {decay.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={decay} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="var(--color-border-muted)" vertical={false} />
              <XAxis dataKey="period" tick={<AxisTick />} axisLine={false} tickLine={false} />
              <YAxis hide domain={['auto', 'auto']} />
              <ReferenceLine y={0} stroke="var(--color-border-default)" />
              <Tooltip
                cursor={{ stroke: 'var(--color-border-default)' }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const point = payload[0].payload as { period: string; value: number | null };
                  return (
                    <div className="factor-tooltip">
                      <div className="factor-tooltip__label">{point.period}</div>
                      <div className="factor-tooltip__value">
                        {point.value === null ? t('factors.library.notMeasured') : corr(point.value, locale)}
                      </div>
                    </div>
                  );
                }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="var(--color-accent-primary)"
                strokeWidth={1.5}
                dot={{ r: 2.5, fill: 'var(--color-accent-primary)' }}
                isAnimationActive={false}
                connectNulls={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <EmptyPlot label={t('factors.library.notMeasured')} />
        )}
      </ChartFrame>

      <ChartFrame
        title={t('factors.library.charts.longShort')}
        note={t('factors.library.charts.longShortNote')}
      >
        {spreads.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={spreads} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="var(--color-border-muted)" vertical={false} />
              <XAxis dataKey="period" tick={<AxisTick />} axisLine={false} tickLine={false} />
              <YAxis hide domain={['auto', 'auto']} />
              <ReferenceLine y={0} stroke="var(--color-border-default)" />
              <Tooltip
                cursor={{ fill: 'var(--color-bg-hover)' }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const point = payload[0].payload as { period: string; spread: number | null };
                  return (
                    <div className="factor-tooltip">
                      <div className="factor-tooltip__label">{point.period}</div>
                      <div className="factor-tooltip__value">
                        {point.spread === null
                          ? t('factors.library.notMeasured')
                          : pct2(point.spread, locale)}
                      </div>
                    </div>
                  );
                }}
              />
              <Bar dataKey="spread" isAnimationActive={false} radius={[2, 2, 0, 0]}>
                {spreads.map((point) => (
                  <Cell key={point.period} fill={signColor(point.spread)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <EmptyPlot label={t('factors.library.notMeasured')} />
        )}
      </ChartFrame>

      <ChartFrame title={t('factors.library.charts.turnover')} note={t('factors.library.charts.turnoverNote')}>
        <div className="factor-chart__stats">
          <Stat
            label={t('factors.library.turnover.top')}
            value={turnover[0]?.value === null ? '—' : pct1(turnover[0]?.value ?? 0, locale)}
          />
          <Stat
            label={t('factors.library.turnover.bottom')}
            value={turnover[1]?.value === null ? '—' : pct1(turnover[1]?.value ?? 0, locale)}
          />
        </div>
        {turnover.some((bar) => bar.value !== null) ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={turnover.map((bar) => ({
                ...bar,
                // Localized here rather than through the tick formatter: the custom
                // tick renders `payload.value` verbatim, so a formatter would be
                // silently ignored and the axis would ship in English on a Chinese page.
                label:
                  bar.label === 'top'
                    ? t('factors.library.turnover.top')
                    : t('factors.library.turnover.bottom'),
              }))}
              margin={{ top: 8, right: 8, bottom: 0, left: 8 }}
            >
              <CartesianGrid stroke="var(--color-border-muted)" vertical={false} />
              <XAxis dataKey="label" tick={<AxisTick />} axisLine={false} tickLine={false} />
              <YAxis hide domain={[0, 'auto']} />
              <Tooltip
                cursor={{ fill: 'var(--color-bg-hover)' }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const point = payload[0].payload as NamedValue;
                  return (
                    <div className="factor-tooltip">
                      <div className="factor-tooltip__label">{point.label}</div>
                      <div className="factor-tooltip__value">
                        {point.value === null ? t('factors.library.notMeasured') : pct1(point.value, locale)}
                      </div>
                    </div>
                  );
                }}
              />
              <Bar
                dataKey="value"
                fill="var(--color-text-secondary)"
                isAnimationActive={false}
                radius={[2, 2, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <EmptyPlot label={t('factors.library.notMeasured')} />
        )}
      </ChartFrame>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="factor-stat">
      <span className="factor-stat__label">{label}</span>
      <span className="factor-stat__value">{value}</span>
    </div>
  );
}

export default FactorCharts;
