/**
 * The factor library: what the desk has kept, and what can be done with it.
 *
 * This is the half the board was missing. A detection answers "what would this
 * script score"; a factor that scored well still had nowhere to live, so it could
 * not be compared, promoted, or re-checked a month later. Here a factor is a row
 * with an economic hypothesis attached, and the panel is built around the three
 * things a reader does with one: read the reasoning, look at the evidence, decide.
 *
 * Layout follows that order deliberately — the hypothesis sits above the code and
 * above the charts, because a factor without a stated reason is data mining and
 * the order is the argument. The lifecycle buttons are grouped last and are quiet:
 * promotion is a record of a judgement, not a call to action.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ChevronDown, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Loader } from '@/components/ui/loader';
import { SegmentedControl } from '@/components/ui/segmented-control';
import {
  type EvaluateFactorRequest,
  type FactorLibraryFilters,
  type FactorLibraryItem,
  type FactorLibrarySummary,
  type FactorStatus,
  type FactorSource,
} from '@/api/factors';
import {
  detectionErrorMessage,
  useDeleteFactor,
  useEvaluateFactor,
  useFactorLibrary,
  useFactorLibraryItem,
  useSaveFactor,
  useSetFactorStatus,
} from '@/hooks/useFactors';
import { FactorCharts } from './FactorCharts';

const STATUS_FILTERS = ['all', 'candidate', 'promoted', 'rejected'] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

const SOURCE_LABEL_KEY: Record<FactorSource, string> = {
  user: 'factors.library.source.user',
  agent: 'factors.library.source.agent',
  sota: 'factors.library.source.sota',
  athena: 'factors.library.source.athena',
};

function sourceLabel(source: string, t: (key: string) => string): string {
  const key = SOURCE_LABEL_KEY[source as FactorSource];
  return key ? t(key) : source;
}

function statusLabel(status: string, t: (key: string) => string): string {
  return t(`factors.library.status.${status}`);
}

function ic(value: number | null | undefined): string {
  return typeof value === 'number' ? value.toFixed(4) : '—';
}

function ir(value: number | null | undefined): string {
  return typeof value === 'number' ? value.toFixed(2) : '—';
}

export function FactorLibraryPanel() {
  const { t } = useTranslation();
  // The chip value and the API filter are two different things on purpose: "all"
  // is a UI answer, and the request for it must omit `status` entirely rather than
  // send a literal the server would reject.
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const filters = useMemo<FactorLibraryFilters>(
    () => ({ status: statusFilter === 'all' ? null : statusFilter, q: query }),
    [statusFilter, query],
  );

  const listQuery = useFactorLibrary(filters);
  const itemQuery = useFactorLibraryItem(selectedId);
  const saveFactor = useSaveFactor();
  const deleteFactor = useDeleteFactor();
  const setStatus = useSetFactorStatus();
  const evaluateFactor = useEvaluateFactor();

  const rows = listQuery.data?.factors ?? [];
  const counts = listQuery.data?.counts ?? {};

  // Open the newest factor once the list arrives, so the panel is never an empty
  // right-hand side next to a full table. Only when nothing is selected yet:
  // re-selecting on every refetch would fight the reader's own click.
  useEffect(() => {
    if (selectedId || !rows.length) return;
    setSelectedId(rows[0].factor_id);
  }, [rows, selectedId]);

  const activeItem = itemQuery.data?.factor_id === selectedId ? itemQuery.data : undefined;

  const statusOptions = useMemo(
    () =>
      STATUS_FILTERS.map((value) => ({
        value,
        label:
          value === 'all'
            ? t('factors.library.filter.all', { count: counts.total ?? 0 })
            : `${statusLabel(value, t)} ${counts[value] ?? 0}`,
      })),
    [counts, t],
  );

  const writeError = saveFactor.isError
    ? detectionErrorMessage(saveFactor.error)
    : setStatus.isError
      ? detectionErrorMessage(setStatus.error)
      : evaluateFactor.isError
        ? detectionErrorMessage(evaluateFactor.error)
        : deleteFactor.isError
          ? detectionErrorMessage(deleteFactor.error)
          : '';

  const onDelete = (item: FactorLibraryItem) => {
    if (!window.confirm(t('factors.library.actions.confirmDelete', { name: item.name }))) return;
    deleteFactor.mutate(item.factor_id, {
      onSuccess: () => setSelectedId(null),
    });
  };

  return (
    <div className="factor-library">
      <section className="factor-library__list" aria-label={t('factors.library.listLabel')}>
        <div className="factor-library__toolbar">
          <SegmentedControl<StatusFilter>
            size="compact"
            value={statusFilter}
            onChange={setStatusFilter}
            options={statusOptions}
          />
          <div className="factor-library__toolbar-right">
            <input
              className="factor-library__search"
              type="search"
              value={query}
              placeholder={t('factors.library.search')}
              onChange={(event) => setQuery(event.target.value)}
              aria-label={t('factors.library.search')}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCreating((prev) => !prev)}
            >
              <Plus size={14} aria-hidden />
              {t('factors.library.actions.new')}
            </Button>
          </div>
        </div>

        {creating && (
          <NewFactorForm
            submitting={saveFactor.isPending}
            onSubmit={(body) => {
              saveFactor.mutate(body, {
                onSuccess: (item) => {
                  setCreating(false);
                  setSelectedId(item.factor_id);
                },
              });
            }}
            onCancel={() => setCreating(false)}
          />
        )}

        {listQuery.isError && (
          <div className="factor-library__banner" role="alert">
            <AlertTriangle size={15} aria-hidden />
            <span>{detectionErrorMessage(listQuery.error)}</span>
          </div>
        )}

        {!listQuery.isLoading && !rows.length && (
          <div className="factor-library__empty">
            <p>{t('factors.library.empty.title')}</p>
            <p className="factor-library__empty-hint">{t('factors.library.empty.hint')}</p>
          </div>
        )}

        {rows.length > 0 && (
          <table className="factor-library__table">
            <thead>
              <tr>
                <th scope="col">{t('factors.library.columns.name')}</th>
                <th scope="col">{t('factors.library.columns.hypothesis')}</th>
                <th scope="col">{t('factors.library.columns.source')}</th>
                <th scope="col">{t('factors.library.columns.status')}</th>
                <th scope="col" className="factor-library__num">
                  IC
                </th>
                <th scope="col" className="factor-library__num">
                  IR
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <LibraryRow
                  key={row.factor_id}
                  row={row}
                  selected={row.factor_id === selectedId}
                  onSelect={() => setSelectedId(row.factor_id)}
                />
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="factor-library__detail" aria-label={t('factors.library.detailLabel')}>
        {writeError && (
          <div className="factor-library__banner factor-library__banner--error" role="alert">
            <AlertTriangle size={15} aria-hidden />
            <span>{writeError}</span>
          </div>
        )}

        {!selectedId && <p className="factor-library__placeholder">{t('factors.library.detail.pick')}</p>}

        {selectedId && itemQuery.isError && (
          <div className="factor-library__banner factor-library__banner--error" role="alert">
            <AlertTriangle size={15} aria-hidden />
            <span>{detectionErrorMessage(itemQuery.error)}</span>
          </div>
        )}

        {activeItem && (
          <FactorDetail
            item={activeItem}
            busy={
              setStatus.isPending || deleteFactor.isPending || evaluateFactor.isPending
            }
            evaluating={activeItem.evaluation.state === 'running'}
            onEvaluate={(body) => evaluateFactor.mutate({ factorId: activeItem.factor_id, body })}
            onStatus={(status) => setStatus.mutate({ factorId: activeItem.factor_id, status })}
            onDelete={() => onDelete(activeItem)}
          />
        )}
      </section>
    </div>
  );
}

function LibraryRow({
  row,
  selected,
  onSelect,
}: {
  row: FactorLibrarySummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  return (
    <tr
      className={`factor-library__row${selected ? ' factor-library__row--selected' : ''}`}
      onClick={onSelect}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect();
        }
      }}
      aria-selected={selected}
    >
      <td className="factor-library__name">{row.name}</td>
      <td className="factor-library__hypothesis" title={row.hypothesis}>
        {row.hypothesis}
      </td>
      <td>
        <span className="factor-library__source">{sourceLabel(row.source, t)}</span>
      </td>
      <td>
        <span className={`factor-library__status factor-library__status--${row.status}`}>
          {statusLabel(row.status, t)}
        </span>
      </td>
      <td className="factor-library__num">{ic(row.ic)}</td>
      <td className="factor-library__num">{ir(row.ir)}</td>
    </tr>
  );
}

function FactorDetail({
  item,
  busy,
  evaluating,
  onEvaluate,
  onStatus,
  onDelete,
}: {
  item: FactorLibraryItem;
  busy: boolean;
  evaluating: boolean;
  onEvaluate: (body: EvaluateFactorRequest) => void;
  onStatus: (status: FactorStatus) => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const [dataset, setDataset] = useState<EvaluateFactorRequest['dataset']>('debug');
  const [showCode, setShowCode] = useState(false);
  const [period, setPeriod] = useState<string | null>(null);

  const evaluation = item.evaluation ?? { state: 'none' as const };
  const periods = useMemo(
    () => Object.keys(item.metrics?.tearsheet?.quantile_returns ?? {}),
    [item.metrics],
  );

  // A period chosen for a previous factor must not leak into this one: the periods
  // a tearsheet measured are its own, so the selector resets with the factor.
  useEffect(() => {
    setPeriod(null);
    setShowCode(false);
  }, [item.factor_id]);

  const evaluatedWindow = evaluation.eval_window;

  return (
    <article className="factor-detail">
      <header className="factor-detail__header">
        <div className="factor-detail__title">
          <h2>{item.name}</h2>
          <span className={`factor-library__status factor-library__status--${item.status}`}>
            {statusLabel(item.status, t)}
          </span>
          <span className="factor-library__source">{sourceLabel(item.source, t)}</span>
        </div>
      </header>

      <section className="factor-detail__hypothesis">
        <h3>{t('factors.library.detail.hypothesis')}</h3>
        <p>{item.hypothesis}</p>
        {evaluation.hypothesis_missing && (
          <p className="factor-detail__warn">{t('factors.library.detail.hypothesisMissing')}</p>
        )}
        {item.formulation && (
          <p className="factor-detail__formulation">
            <span>{t('factors.library.detail.formulation')}</span>
            <code>{item.formulation}</code>
          </p>
        )}
      </section>

      <section className="factor-detail__evidence">
        <div className="factor-detail__evidence-head">
          <h3>{t('factors.library.detail.evidence')}</h3>
          {evaluating && (
            <span className="factor-detail__live">
              <Loader size={11} style={{ color: 'var(--color-accent-primary)' }} />
              {t('factors.library.evaluation.running')}
            </span>
          )}
        </div>

        {evaluation.state === 'failed' || evaluation.state === 'lost' ? (
          <div className="factor-library__banner factor-library__banner--error" role="alert">
            <AlertTriangle size={15} aria-hidden />
            <span>
              {evaluation.state === 'lost'
                ? t('factors.library.evaluation.lost')
                : t('factors.library.evaluation.failed')}
              {evaluation.error ? ` · ${evaluation.error}` : ''}
            </span>
          </div>
        ) : null}

        {evaluation.state === 'none' && !evaluating && (
          <p className="factor-library__placeholder">{t('factors.library.evaluation.none')}</p>
        )}

        {item.metrics?.tearsheet && (
          <>
            <div className="factor-detail__meta">
              <span>
                {t('factors.library.detail.dataset')}:{' '}
                <b>{evaluation.dataset ?? '—'}</b>
              </span>
              <span>
                {t('factors.library.detail.symbols')}: <b>{evaluation.n_symbols ?? '—'}</b>
              </span>
              <span>
                {t('factors.library.detail.dates')}: <b>{evaluation.n_dates ?? '—'}</b>
              </span>
              {evaluatedWindow?.start && (
                <span>
                  {t('factors.library.detail.window')}:{' '}
                  <b>
                    {evaluatedWindow.start} → {evaluatedWindow.end}
                  </b>
                </span>
              )}
              {typeof evaluation.window_days === 'number' && evaluation.window_days > 0 && (
                <span>
                  {t('factors.library.detail.windowDays')}: <b>{evaluation.window_days}</b>
                </span>
              )}
            </div>
            {periods.length > 1 && (
              <div className="factor-detail__periods">
                <span>{t('factors.library.detail.period')}</span>
                <SegmentedControl<string>
                  size="compact"
                  value={period ?? periods[0]}
                  onChange={setPeriod}
                  options={periods.map((value) => ({ value, label: value }))}
                />
              </div>
            )}
            <FactorCharts item={item} period={period ?? periods[0] ?? null} />
          </>
        )}

        {!item.metrics?.tearsheet && evaluating && (
          <p className="factor-library__placeholder">{t('factors.library.evaluation.runningNote')}</p>
        )}
      </section>

      <section className="factor-detail__code">
        <button type="button" className="factor-detail__toggle" onClick={() => setShowCode((v) => !v)}>
          <ChevronDown size={14} className={showCode ? 'factor-detail__chevron--open' : ''} aria-hidden />
          {t('factors.library.detail.code')}
          <code className="factor-detail__hash">{item.code_hash.slice(0, 8)}</code>
        </button>
        {showCode && <pre className="factor-detail__source">{item.code}</pre>}
      </section>

      <section className="factor-detail__actions">
        <div className="factor-detail__evaluate">
          <SegmentedControl<EvaluateFactorRequest['dataset'] & string>
            size="compact"
            value={dataset ?? 'debug'}
            onChange={setDataset}
            options={[
              { value: 'debug', label: t('factors.library.actions.datasetDebug') },
              { value: 'full', label: t('factors.library.actions.datasetFull') },
            ]}
          />
          <Button
            size="sm"
            disabled={busy || evaluating}
            onClick={() => onEvaluate({ dataset: dataset ?? 'debug' })}
          >
            {evaluating ? (
              <Loader size={11} style={{ color: 'var(--color-text-secondary)' }} />
            ) : null}
            {evaluating
              ? t('factors.library.actions.evaluating')
              : t('factors.library.actions.evaluate')}
          </Button>
        </div>
        <div className="factor-detail__lifecycle">
          <Button
            variant="outline"
            size="sm"
            disabled={busy || item.status === 'promoted'}
            onClick={() => onStatus('promoted')}
          >
            {t('factors.library.actions.promote')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || item.status === 'rejected'}
            onClick={() => onStatus('rejected')}
          >
            {t('factors.library.actions.reject')}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={onDelete}
            aria-label={t('factors.library.actions.delete')}
          >
            <Trash2 size={14} aria-hidden />
          </Button>
        </div>
      </section>
    </article>
  );
}

/**
 * The save form.
 *
 * The hypothesis is a textarea and not an input on purpose: it is the field the
 * library exists for, and a one-line box invites a one-line answer. The server
 * refuses an empty one, and this form refuses to submit one, so the rule is
 * stated where the factor is written rather than discovered as a 422.
 */
function NewFactorForm({
  submitting,
  onSubmit,
  onCancel,
}: {
  submitting: boolean;
  onSubmit: (body: {
    name: string;
    hypothesis: string;
    code: string;
    formulation?: string;
  }) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [hypothesis, setHypothesis] = useState('');
  const [formulation, setFormulation] = useState('');
  const [code, setCode] = useState('');

  const ready = name.trim() && hypothesis.trim() && code.trim();

  return (
    <form
      className="factor-library__new"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready || submitting) return;
        onSubmit({
          name: name.trim(),
          hypothesis: hypothesis.trim(),
          code,
          formulation: formulation.trim() || undefined,
        });
      }}
    >
      <div className="factor-library__new-row">
        <label>
          {t('factors.library.columns.name')}
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={64} spellCheck={false} />
        </label>
        <label>
          {t('factors.library.detail.formulation')}
          <input value={formulation} onChange={(e) => setFormulation(e.target.value)} spellCheck={false} />
        </label>
      </div>
      <label className="factor-library__new-wide">
        {t('factors.library.detail.hypothesis')}
        <textarea
          value={hypothesis}
          onChange={(e) => setHypothesis(e.target.value)}
          rows={2}
          placeholder={t('factors.library.new.hypothesisPlaceholder')}
        />
      </label>
      <label className="factor-library__new-wide">
        {t('factors.library.detail.code')}
        <textarea
          className="factor-library__new-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          rows={6}
          spellCheck={false}
          placeholder={'import pandas as pd\n...'}
        />
      </label>
      <div className="factor-library__new-actions">
        <Button type="submit" size="sm" disabled={!ready || submitting}>
          {t('factors.library.new.save')}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          {t('factors.library.new.cancel')}
        </Button>
      </div>
    </form>
  );
}

export default FactorLibraryPanel;
