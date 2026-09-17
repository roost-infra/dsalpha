import { CheckCircle2, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { DetectionRun, IcProbe, OosFinding } from '@/api/factors';

/** Presentation scale for the IC bars — the same thresholds the verdict uses. */
const IC_AXIS = 0.06;

/** Fields the OOS stage reports, in the order a reader asks for them. */
const OOS_METRICS: Array<{ key: string; labelKey: string; percent?: boolean }> = [
  { key: 'ic', labelKey: 'factors.oos.ic' },
  { key: 'annualized_return', labelKey: 'factors.oos.annualized', percent: true },
  { key: 'max_drawdown', labelKey: 'factors.oos.drawdown', percent: true },
];

function formatValue(value: unknown, percent = false): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return percent ? `${(value * 100).toFixed(1)}%` : value.toFixed(4);
}

/**
 * One IC probe as a signed bar.
 *
 * The sign is the factor's direction, so a bar is drawn from a centre line
 * outwards: a positive IC and a negative one are equally informative here (the
 * verdict reads magnitude), and a bar anchored at zero would hide that.
 */
function IcBar({ probe }: { probe: IcProbe }) {
  const { t } = useTranslation();
  const ic = probe.ic;
  if (typeof ic !== 'number') {
    return (
      <div className="factor-ic__row">
        <span className="factor-ic__label">{t('factors.ic.window', { days: probe.window })}</span>
        <span className="factor-ic__value factor-ic__value--muted">
          {probe.error || t('factors.ic.none')}
        </span>
      </div>
    );
  }

  const ratio = Math.min(Math.abs(ic) / IC_AXIS, 1);
  const positive = ic >= 0;
  return (
    <div className="factor-ic__row">
      <span className="factor-ic__label">{t('factors.ic.window', { days: probe.window })}</span>
      <div className="factor-ic__track" aria-hidden>
        <span className="factor-ic__mid" />
        <span
          className={`factor-ic__bar factor-ic__bar--${positive ? 'up' : 'down'}`}
          style={{
            width: `${(ratio * 50).toFixed(1)}%`,
            [positive ? 'left' : 'right']: '50%',
          }}
        />
      </div>
      <span className={`factor-ic__value${positive ? '' : ' factor-ic__value--down'}`}>
        {ic >= 0 ? '+' : ''}
        {ic.toFixed(4)}
      </span>
    </div>
  );
}

function OosTable({ oos }: { oos: OosFinding }) {
  const { t } = useTranslation();
  return (
    <table className="factor-table">
      <thead>
        <tr>
          <th>{t('factors.oos.metric')}</th>
          <th>{t('factors.oos.mining')}</th>
          <th>{t('factors.oos.oos')}</th>
        </tr>
      </thead>
      <tbody>
        {OOS_METRICS.map((metric) => (
          <tr key={metric.key}>
            <td>{t(metric.labelKey)}</td>
            <td>{formatValue(oos.mining?.[metric.key], metric.percent)}</td>
            <td>{formatValue(oos.oos?.[metric.key], metric.percent)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * What the detection found, under the verdict.
 *
 * Ordered by how much each part should change a decision: the contract first
 * (a factor that fails it has no number worth reading), then the IC probes, then
 * the sample-out comparison, which is advisory — it refines a verdict rather
 * than gating one.
 */
export function DetectionReport({ run }: { run: DetectionRun }) {
  const { t } = useTranslation();
  const verdict = run.verdict;
  const contract = run.findings.contract;
  const probes = run.findings.recent_ic ?? [];
  const oos = run.findings.oos;
  const level = verdict.level ?? 'unknown';

  return (
    <div className="factor-report">
      <div className={`factor-verdict factor-verdict--${level}`}>
        <div className="factor-verdict__head">
          <span className="factor-verdict__label">{verdict.label ?? t('factors.report.noVerdict')}</span>
          {typeof verdict.ic === 'number' && (
            <span className="factor-verdict__ic">
              IC {verdict.ic >= 0 ? '+' : ''}
              {verdict.ic.toFixed(4)}
            </span>
          )}
        </div>
        {verdict.summary && <p className="factor-verdict__summary">{verdict.summary}</p>}
        {/* A run that failed before or during the probes has no numbers to show,
            so its own reason is the whole report. The verdict still renders —
            it is the reading of what did come back, and "no usable IC" is a
            finding, not an empty state. */}
        {run.status === 'failed' && run.error && (
          <p className="factor-verdict__error" role="alert">
            {run.error}
          </p>
        )}
        <div className="factor-verdict__meta">
          <code>{run.run_id}</code>
          <span>{t('factors.report.elapsed', { seconds: Math.round(run.elapsed_sec) })}</span>
        </div>
      </div>

      <section className="factor-card">
        <h3>{t('factors.contract.title')}</h3>
        <div className="factor-contract">
          {contract?.ok ? (
            <CheckCircle2 size={16} className="factor-stage__icon--done" aria-hidden />
          ) : (
            <XCircle size={16} className="factor-stage__icon--failed" aria-hidden />
          )}
          <span>{contract?.detail || t('factors.contract.unknown')}</span>
        </div>
        {contract?.stdout && <pre className="factor-pre">{contract.stdout}</pre>}
      </section>

      {probes.length > 0 && (
        <section className="factor-card">
          <h3>{t('factors.ic.title')}</h3>
          <div className="factor-ic">
            {probes.map((probe) => (
              <IcBar key={probe.window} probe={probe} />
            ))}
          </div>
          <p className="factor-card__note">{t('factors.ic.note')}</p>
        </section>
      )}

      {oos && (oos.mining || oos.oos) && (
        <section className="factor-card">
          <h3>{t('factors.oos.title')}</h3>
          <OosTable oos={oos} />
          {typeof oos.decay === 'number' && (
            <p className="factor-card__note">
              {t('factors.oos.decay', { value: `${(oos.decay * 100).toFixed(1)}%` })}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
