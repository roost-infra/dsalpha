import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ArrowUpRight, Download, FileSpreadsheet } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';

import { apiErrorStatus } from '@/api/errors';
import { Button } from '@/components/ui/button';
import { Loader } from '@/components/ui/loader';
import { useLocale } from '@/hooks/useLocale';
import { formatTimestamp } from '@/lib/format';
import { cn } from '@/lib/utils';

import { getQuarter, type Metric, type Observation } from './quarterData';
import { exportBrief, exportWorkbook } from './quarterExport';
import { ResearchSearch } from './ResearchSearch';

const fields = ['current', 'previous', 'year_ago'] as const;
const externalLink = 'inline-flex items-center gap-1 font-medium text-foreground underline-offset-4 hover:underline focus-visible:underline';

function Evidence({ metric, number }: { metric: Metric; number: (value: number) => string }) {
  const { t } = useTranslation();
  return (
    <aside aria-label={t('research.evidence')} className="min-w-0 lg:border-l lg:pl-6">
      <h2 className="text-base font-semibold">{t('research.evidence')}</h2>
      <h3 className="mt-3 text-sm font-medium">{t(`research.metrics.${metric.key}`)}</h3>
      <div className="mt-2 divide-y border-y">
        {fields.map((field) => {
          const observation = metric[field];
          if (!observation) return null;
          return (
            <section className="py-3" key={field}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
                <span className="font-medium">{t(`research.${field}`)}</span>
                <span className="tabular-nums">{number(observation.value)} USD</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{t(`research.${observation.method}`)}</p>
              <ul className="mt-2 space-y-3 text-xs">
                {observation.evidence.map((fact) => (
                  <li key={`${fact.accession}:${fact.start}:${fact.end}`} className="grid gap-1">
                    <a href={fact.url} target="_blank" rel="noreferrer" className={externalLink}>
                      {fact.form} · {fact.filed}
                      <ArrowUpRight className="size-3.5" aria-hidden="true" />
                    </a>
                    <span className="break-all text-muted-foreground">{fact.tag}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {fact.start} – {fact.end} · {fact.sign < 0 ? '− ' : ''}{number(fact.value)} USD
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </aside>
  );
}

export default function QuarterResearch() {
  const { t } = useTranslation();
  const locale = useLocale();
  const { symbol = '' } = useParams();
  const ticker = symbol.toUpperCase();
  const [params, setParams] = useSearchParams();
  const period = params.get('period');
  const [selectedMetric, setSelectedMetric] = useState<Metric['key']>('revenue');
  const [exportError, setExportError] = useState(false);
  const [exporting, setExporting] = useState(false);
  const query = useQuery({
    queryKey: ['research', 'quarter', ticker, period],
    queryFn: ({ signal }) => getQuarter(ticker, period, signal),
    staleTime: ({ state }) => state.data?.stale ? 60_000 : 5 * 60_000,
    retry: false,
  });
  const quarter = query.data;
  const metric = quarter?.metrics.find((item) => item.key === selectedMetric) ?? quarter?.metrics[0];
  const numbers = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  const compact = new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 2 });
  const percents = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1, signDisplay: 'exceptZero' });
  const percent = (value: number | null) => value == null ? '—' : percents.format(value);
  const value = (observation: Observation | null) => observation ? compact.format(observation.value) : '—';

  async function saveExcel() {
    if (!quarter) return;
    setExportError(false);
    setExporting(true);
    try {
      await exportWorkbook(quarter, t);
    } catch {
      setExportError(true);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page">
      <div className="mx-auto grid max-w-6xl gap-5 px-4 py-5 sm:px-6">
        <Link to="/dashboard" className="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" aria-hidden="true" /> {t('sidebar.dashboard')}
        </Link>
        <ResearchSearch key={ticker} initialSymbol={ticker} />
        <header className="grid gap-2 border-b pb-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-2xl font-semibold">{ticker}</h1>
            {quarter && <span className="text-sm text-muted-foreground">{quarter.company}</span>}
          </div>
          {quarter && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
              <span>{t('research.periodEnd', { date: quarter.selected.end })}</span>
              <a href={quarter.selected.url} target="_blank" rel="noreferrer" className={externalLink}>
                {quarter.selected.form} · {quarter.selected.filed}<ArrowUpRight className="size-3.5" aria-hidden="true" />
              </a>
              <span>{t('research.retrieved', { time: formatTimestamp(quarter.fetched_at, locale) })}</span>
              {quarter.stale && <span role="status">{t('research.cachedData')}</span>}
            </div>
          )}
        </header>
        {query.isPending && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader size={14} /> {t('research.loading')}
          </p>
        )}
        {query.isError && (
          <div className="flex flex-wrap items-center gap-3">
            <p role="alert" className="text-sm text-destructive">{t(apiErrorStatus(query.error) === 404 ? 'research.notFound' : 'research.failed')}</p>
            {period && <Button size="sm" variant="outline" onClick={() => setParams({})}>{t('research.latest')}</Button>}
            <Button size="sm" variant="outline" onClick={() => void query.refetch()}>{t('computer.cloud.retry')}</Button>
          </div>
        )}
        {quarter && (
          <section className="min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-base font-semibold">{t('research.comparisons')}</h2>
              <select
                aria-label={t('research.period')}
                className="h-9 max-w-full rounded-md border bg-page px-2 text-sm"
                value={period ?? ''}
                onChange={(event) => setParams(event.target.value ? { period: event.target.value } : {})}
              >
                <option value="">{t('research.latest')} · {quarter.periods[0]?.end}</option>
                {quarter.periods.map((filing) => (
                  <option value={filing.end} key={filing.accession}>{filing.end} · {filing.form}</option>
                ))}
              </select>
            </div>
            {!metric && <p role="status" className="mt-3 text-sm text-muted-foreground">{t('research.noMetrics')}</p>}
          </section>
        )}
        {quarter && metric && (
          <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(17rem,0.55fr)]">
            <section className="min-w-0">
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[28rem] border-y text-sm">
                  <thead className="text-xs text-muted-foreground">
                    <tr className="border-b">
                      <th className="px-2 py-3 text-left font-medium" scope="col">{t('research.metric')} · USD</th>
                      {['current', 'previous', 'qoq', 'yoy'].map((field) => (
                        <th className="px-2 py-3 text-right font-medium" scope="col" key={field}>{t(`research.${field}`)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {quarter.metrics.map((item) => (
                      <tr key={item.key} className={cn(item.key === metric.key && 'bg-muted/45')}>
                        <th className="px-2 py-3 text-left font-medium" scope="row">
                          <button className="text-left underline-offset-4 hover:underline" type="button" aria-pressed={item.key === metric.key}
                            onClick={() => setSelectedMetric(item.key)}>{t(`research.metrics.${item.key}`)}</button>
                        </th>
                        {[value(item.current), value(item.previous), percent(item.qoq), percent(item.yoy)].map((display, index) => (
                          <td className="whitespace-nowrap px-2 py-3 text-right tabular-nums" key={index}>{display}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => exportBrief(quarter, t, percent)}>
                  <Download aria-hidden="true" /> {t('research.brief')}
                </Button>
                <Button variant="outline" size="sm" onClick={() => void saveExcel()} disabled={exporting}>
                  {exporting ? <Loader size={14} /> : <FileSpreadsheet aria-hidden="true" />} {t('research.excel')}
                </Button>
              </div>
              {exportError && <p role="alert" className="mt-2 text-sm text-destructive">{t('research.exportFailed')}</p>}
            </section>
            <Evidence metric={metric} number={(amount) => numbers.format(amount)} />
          </div>
        )}
      </div>
    </div>
  );
}
