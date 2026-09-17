import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, FlaskConical, Loader2, Play } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  detectionErrorMessage,
  useDetection,
  useFactorMinerHealth,
  useFactorTemplates,
  useStartDetection,
} from '@/hooks/useFactors';
import type { DetectionRun, FactorTemplate } from '@/api/factors';
import { DetectionReport } from './components/DetectionReport';
import { RunProgress } from './components/RunProgress';
import './FactorBoard.css';

/**
 * /factors — the Factor Board.
 *
 * The desk already mines factors; what it could not do was *look* at one. This
 * page closes that loop: paste (or pick) a factor script, press one button, and
 * get a verdict backed by the miner's own probes — the result.h5 contract check,
 * trailing cross-sectional IC over two horizons, and the sample-out comparison.
 *
 * Two decisions shape the layout. First, the editor and the report sit side by
 * side rather than in a wizard: the question a factor author asks is "what did
 * this code score", and answering it should not cost a navigation. Second, the
 * poll is the source of truth for everything after submit — the run carries its
 * own stage list, so progress is rendered from the server's account of what it is
 * doing, not from a client-side guess about how long a step should take.
 *
 * The code is held in state per mount and never persisted: a factor board is a
 * scratchpad. A run submitted from this page stays inspectable after a reload
 * only through the server's ledger, which is why the page also accepts a
 * `?run=<id>` deep link — that is how a link to a finished detection is shared.
 */
function FactorBoard() {
  const { t } = useTranslation();
  const templatesQuery = useFactorTemplates();
  const healthQuery = useFactorMinerHealth();
  const startDetection = useStartDetection();

  const [name, setName] = useState('reversal_20');
  const [code, setCode] = useState('');
  const [templateKey, setTemplateKey] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);

  // Seed the editor once, from the first template, and never again: a later
  // refetch (or a re-render) must not overwrite what the user has typed.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    const templates = templatesQuery.data;
    if (!templates?.length) return;
    seeded.current = true;
    const first = templates[0];
    setCode(first.code);
    setTemplateKey(first.key);
    setName(first.key);
  }, [templatesQuery.data]);

  // ?run=<id> — a shareable link to a detection the server still holds.
  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get('run');
    if (fromUrl && !runId) setRunId(fromUrl);
    // Intentionally runs once: after this the URL is an output of state, not an
    // input to it, and re-reading it on every render would fight the run picker.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runQuery = useDetection(runId);
  const run = runQuery.data;

  const pickTemplate = (template: FactorTemplate) => {
    setTemplateKey(template.key);
    setCode(template.code);
    setName(template.key);
  };

  const onStart = () => {
    startDetection.mutate(
      { name: name.trim() || 'factor', code, debug: true, include_oos: true },
      {
        onSuccess: (started) => {
          setRunId(started.run_id);
          const url = new URL(window.location.href);
          url.searchParams.set('run', started.run_id);
          window.history.replaceState(null, '', url.toString());
        },
      },
    );
  };

  // The run the page is currently following, whether it just started (mutation
  // result) or was picked up from the ledger (query).
  const activeRun: DetectionRun | undefined = run ?? startDetection.data ?? undefined;
  const isRunning = activeRun?.status === 'running' || activeRun?.status === 'queued';
  const submitError = startDetection.isError
    ? detectionErrorMessage(startDetection.error)
    : '';

  // A 404 on the poll means the server no longer holds the run (it restarted, or
  // the ledger expired) — distinct from "still running", and actionable.
  const pollError = runQuery.isError ? detectionErrorMessage(runQuery.error) : '';

  const upstreamWarning = useMemo(() => {
    const health = healthQuery.data;
    if (!health) return null;
    if (!health.configured) return t('factors.health.unconfigured');
    if (!health.reachable) return t('factors.health.unreachable');
    return null;
  }, [healthQuery.data, t]);

  return (
    <div className="factor-board">
      <header className="factor-board__header">
        <div className="factor-board__title">
          <FlaskConical size={18} aria-hidden />
          <h1>{t('factors.title')}</h1>
          <span className="factor-board__subtitle">{t('factors.subtitle')}</span>
        </div>
        <div className="factor-board__health">
          <span
            className={`factor-board__dot factor-board__dot--${
              healthQuery.data?.reachable ? 'ok' : 'bad'
            }`}
            aria-hidden
          />
          {healthQuery.data?.reachable
            ? t('factors.health.ok', { url: healthQuery.data.url })
            : t('factors.health.down')}
        </div>
      </header>

      {upstreamWarning && (
        <div className="factor-board__banner" role="status">
          <AlertTriangle size={16} aria-hidden />
          <span>{upstreamWarning}</span>
        </div>
      )}

      <div className="factor-board__body">
        <section className="factor-board__editor" aria-label={t('factors.editor.label')}>
          <div className="factor-board__field">
            <label htmlFor="factor-name">{t('factors.editor.name')}</label>
            <input
              id="factor-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={64}
              spellCheck={false}
            />
          </div>

          <div className="factor-board__templates">
            <span className="factor-board__templates-label">{t('factors.editor.templates')}</span>
            <div className="factor-board__chips">
              {(templatesQuery.data ?? []).map((template) => (
                <button
                  key={template.key}
                  type="button"
                  className={`factor-board__chip${
                    templateKey === template.key ? ' factor-board__chip--active' : ''
                  }`}
                  onClick={() => pickTemplate(template)}
                  title={template.description}
                >
                  {template.name}
                </button>
              ))}
            </div>
          </div>

          <CodeEditor value={code} onChange={setCode} label={t('factors.editor.label')} />

          <div className="factor-board__actions">
            <Button onClick={onStart} disabled={!code.trim() || isRunning}>
              {isRunning ? <Loader2 size={15} className="spin" aria-hidden /> : <Play size={15} aria-hidden />}
              {isRunning ? t('factors.editor.running') : t('factors.editor.run')}
            </Button>
            {submitError && (
              <span className="factor-board__error" role="alert">
                {submitError}
              </span>
            )}
          </div>
        </section>

        <section className="factor-board__report" aria-label={t('factors.report.label')}>
          {/* A failed poll outranks whatever the cached run says. The seeded copy
              is the state at submit time, so rendering it here would show
              "detecting" for a run the server can no longer speak for — and the
              last thing a reader should be told about a broken poll is that their
              detection is progressing. */}
          {pollError ? (
            <div className="factor-board__banner factor-board__banner--error" role="alert">
              <AlertTriangle size={16} aria-hidden />
              <span>{pollError}</span>
            </div>
          ) : (
            <>
              {!activeRun && (
                <div className="factor-board__empty">
                  <FlaskConical size={28} aria-hidden />
                  <p>{t('factors.report.empty')}</p>
                </div>
              )}
              {activeRun && isRunning && <RunProgress run={activeRun} />}
              {activeRun && !isRunning && (
                <DetectionReport run={activeRun} />
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}

/**
 * A textarea with a line-number gutter, not a full editor.
 *
 * Monaco is already a dependency, but a factor script is 20 lines pasted from a
 * research notebook: the weight and the lazy chunk belong to the chat viewer's
 * HTML case, not here. The gutter is what makes a stack-trace line number
 * meaningful when the sandbox rejects a script.
 */
function CodeEditor({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (next: string) => void;
  label: string;
}) {
  const lines = value.split('\n').length;
  return (
    <div className="factor-board__code">
      <div className="factor-board__gutter" aria-hidden>
        {Array.from({ length: lines }, (_, index) => (
          <span key={index}>{index + 1}</span>
        ))}
      </div>
      <textarea
        className="factor-board__textarea"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
        wrap="off"
        aria-label={label}
      />
    </div>
  );
}

export default FactorBoard;
