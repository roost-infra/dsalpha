import { useTranslation } from 'react-i18next';

import type { IcPoint } from '@/api/factors';

import { buildIcCurve, formatIcDate, IC_STRONG, IC_WEAK, zeroLine, type CurveConfig } from '../utils/icCurve';

/**
 * Geometry for the decay sparkline. Kept at module scope so a re-render does not
 * produce a new object (which would defeat any future memoisation), and so the
 * SVG viewBox and the geometry config cannot drift apart.
 */
const VIEW = { width: 320, height: 72 };
const CFG: CurveConfig = {
  width: VIEW.width,
  height: VIEW.height,
  padTop: 8,
  padBottom: 12,
  bound: 0.05, // replaced per-chart below
};

/**
 * Per-day IC over a probe window.
 *
 * Rendered as a plain SVG polyline rather than the candlestick chart library:
 * this is a 20–60 point sparkline, and pulling in a second charting engine (plus
 * its time-axis handling) for it would cost more than it explains.
 *
 * A single-point series draws a dot — an empty polyline would read as "no data"
 * when there is in fact exactly one observation.
 */
export function IcCurveChart({
  series,
  bound,
  window,
}: {
  series: IcPoint[];
  /** Symmetric y bound, shared across windows so the curves are comparable. */
  bound: number;
  window: number;
}) {
  const { t } = useTranslation();
  const cfg: CurveConfig = { ...CFG, bound };
  const curve = buildIcCurve(series, cfg);
  const baseline = zeroLine(cfg);

  if (curve.points.length === 0) {
    return (
      <div className="factor-ic-curve factor-ic-curve--empty">
        <span className="factor-ic__value factor-ic__value--muted">{t('factors.ic.none')}</span>
      </div>
    );
  }

  const label = t('factors.ic.window', { days: window });
  // The last observation is what a reader compares against "now".
  const last = curve.points[curve.points.length - 1];
  const lastIc = last.ic;
  const positive = lastIc >= 0;

  return (
    <figure className="factor-ic-curve">
      <figcaption className="factor-ic-curve__caption">
        <span className="factor-ic__label">{label}</span>
        <span className={`factor-ic__value${positive ? '' : ' factor-ic__value--down'}`}>
          {t('factors.ic.last', {
            value: `${positive ? '+' : ''}${lastIc.toFixed(4)}`,
          })}
        </span>
      </figcaption>

      <svg
        viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
        className="factor-ic-curve__svg"
        preserveAspectRatio="none"
        role="img"
        aria-label={t('factors.ic.curveAria', {
          days: window,
          value: lastIc.toFixed(4),
          points: curve.points.length,
        })}
      >
        {/* ±弱/强 参考线：0.02 / 0.05 与结论阈值同一口径 */}
        {[IC_WEAK, IC_STRONG, -IC_WEAK, -IC_STRONG].map((level) => {
          const ratio = level / bound;
          const y = cfg.padTop + ((cfg.height - cfg.padTop - cfg.padBottom) / 2) * (1 - ratio);
          if (!Number.isFinite(y) || y < cfg.padTop || y > cfg.height - cfg.padBottom) return null;
          return (
            <line
              key={level}
              x1={0}
              x2={VIEW.width}
              y1={y}
              y2={y}
              className={`factor-ic-curve__guide${Math.abs(level) === IC_STRONG ? ' factor-ic-curve__guide--strong' : ''}`}
            />
          );
        })}
        {/* 零线：IC 有符号，零是分界而不是脚下 */}
        <path d={baseline.path} className="factor-ic-curve__zero" />
        {curve.single ? (
          <circle cx={last.x} cy={last.y} r={2.5} className="factor-ic-curve__dot" />
        ) : (
          <path d={curve.path} className="factor-ic-curve__line" />
        )}
      </svg>

      <div className="factor-ic-curve__meta">
        {curve.peak && (
          <span>
            {t('factors.ic.peak', {
              date: formatIcDate(curve.peak.date),
              value: `${curve.peak.ic >= 0 ? '+' : ''}${curve.peak.ic.toFixed(4)}`,
            })}
          </span>
        )}
        {curve.meanN !== null && (
          <span>{t('factors.ic.meanN', { value: Math.round(curve.meanN) })}</span>
        )}
        <span>{t('factors.ic.points', { count: curve.points.length })}</span>
      </div>
    </figure>
  );
}
