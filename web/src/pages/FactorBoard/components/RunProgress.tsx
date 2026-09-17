import { CheckCircle2, Circle, Loader2, MinusCircle, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { DetectionRun, DetectionStage } from '@/api/factors';

/**
 * The stage list a running detection publishes.
 *
 * Rendered from the server's own stage states rather than from a local timer:
 * the honest unit here is "the contract check passed, the IC probes are running",
 * and a client-side progress bar would have to invent a duration for a probe that
 * takes anywhere from one to five minutes depending on the panel.
 */
function StageIcon({ state }: { state: DetectionStage['state'] }) {
  switch (state) {
    case 'running':
      return <Loader2 size={15} className="spin" aria-hidden />;
    case 'done':
      return <CheckCircle2 size={15} className="factor-stage__icon--done" aria-hidden />;
    case 'failed':
      return <XCircle size={15} className="factor-stage__icon--failed" aria-hidden />;
    case 'skipped':
      return <MinusCircle size={15} className="factor-stage__icon--muted" aria-hidden />;
    default:
      return <Circle size={15} className="factor-stage__icon--muted" aria-hidden />;
  }
}

export function RunProgress({ run }: { run: DetectionRun }) {
  const { t } = useTranslation();
  const done = run.stages.filter((stage) => stage.state === 'done').length;

  return (
    <div className="factor-progress">
      <div className="factor-progress__head">
        <div>
          <h2>{t('factors.progress.title', { name: run.name })}</h2>
          <p className="factor-progress__meta">
            {t('factors.progress.meta', {
              done,
              total: run.stages.length,
              elapsed: Math.round(run.elapsed_sec),
            })}
          </p>
        </div>
        <code className="factor-progress__id">{run.run_id}</code>
      </div>

      <ol className="factor-progress__stages">
        {run.stages.map((stage) => (
          <li key={stage.key} className={`factor-stage factor-stage--${stage.state}`}>
            <StageIcon state={stage.state} />
            <div className="factor-stage__body">
              <span className="factor-stage__label">{stage.label}</span>
              {stage.detail && <span className="factor-stage__detail">{stage.detail}</span>}
            </div>
            {stage.elapsed_sec !== null && stage.state !== 'pending' && (
              <span className="factor-stage__elapsed">{stage.elapsed_sec.toFixed(1)}s</span>
            )}
          </li>
        ))}
      </ol>

      <p className="factor-progress__note">{t('factors.progress.note')}</p>
    </div>
  );
}
