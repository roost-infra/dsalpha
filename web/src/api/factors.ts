/**
 * Factor Board endpoints.
 *
 * The board is a two-call surface by necessity: the miner's IC probes scan the
 * full A-share panel and run for minutes, so a detection is submitted once and
 * then polled. Nothing here caches or merges results — a poll is the answer.
 */
import { api } from '@/api/client';

/** One step of a detection, published so a minutes-long wait is legible. */
export interface DetectionStage {
  key: string;
  label: string;
  state: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  detail: string;
  elapsed_sec: number | null;
}

/** The miner's contract check on the debug panel. */
export interface ContractFinding {
  ok?: boolean;
  detail?: string;
  stdout?: string;
  dataset?: string;
}

/** One point of the per-day IC breakdown, for the decay curve. */
export interface IcPoint {
  /** ISO `YYYY-MM-DD`. */
  date: string;
  ic: number;
  /** Cross-section size behind this point — a thin day's IC is not comparable. */
  n?: number | null;
}

/** One trailing-window cross-sectional IC probe. */
export interface IcProbe {
  window: number;
  ic: number | null;
  days?: number | null;
  /**
   * Per-day IC over the window (ascending by date). Empty when the miner
   * predates the series field or the probe failed — the board then falls back to
   * the scalar probe only.
   */
  series?: IcPoint[];
  error?: string;
}

/** One point of a backtest net-value curve. */
export interface NetCurvePoint {
  /**
   * ISO `YYYY-MM-DD`, or `null` when the miner could not read trading dates
   * (it then falls back to `i`, the trading-day index).
   */
  date: string | null;
  /** Trading-day index within the backtest. Kept even when `date` is present. */
  i: number;
  /** Account equity as qlib recorded it (not a cumulative product we rebuilt). */
  value: number;
}

/** Mining-window vs out-of-sample performance, plus the relative decay. */
export interface OosFinding {
  mining?: Record<string, number | null> | null;
  oos?: Record<string, number | null> | null;
  decay?: number | null;
  /**
   * Equity curves for the two windows, already downsampled by the miner
   * (<=400 points each). Empty when the window failed or predates this field —
   * the chart is skipped rather than drawn empty.
   */
  mining_net_curve?: NetCurvePoint[] | null;
  oos_net_curve?: NetCurvePoint[] | null;
  ok?: boolean | null;
  error?: string | null;
}

export interface DetectionFindings {
  contract?: ContractFinding;
  recent_ic?: IcProbe[];
  oos?: OosFinding;
  [key: string]: unknown;
}

export interface DetectionVerdict {
  level?: 'strong' | 'present' | 'faint' | 'invalid' | 'unknown';
  label?: string;
  summary?: string;
  ic?: number | null;
  ic_label?: string | null;
}

export interface DetectionRun {
  run_id: string;
  name: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  current_stage: string;
  created_at: number;
  elapsed_sec: number;
  stages: DetectionStage[];
  findings: DetectionFindings;
  verdict: DetectionVerdict;
  error: string;
  error_kind: string;
}

export interface FactorTemplate {
  key: string;
  name: string;
  description: string;
  code: string;
}

export interface FactorMinerHealth {
  configured: boolean;
  reachable: boolean;
  url: string;
  version?: string | null;
  auth?: boolean;
  error?: string;
}

export interface DetectionRequest {
  name: string;
  code: string;
  debug?: boolean;
  include_oos?: boolean;
}

export async function getFactorMinerHealth(): Promise<FactorMinerHealth> {
  const { data } = await api.get<FactorMinerHealth>('/api/v1/factors/health');
  return data;
}

export async function getFactorTemplates(): Promise<FactorTemplate[]> {
  const { data } = await api.get<{ templates: FactorTemplate[] }>('/api/v1/factors/templates');
  return data.templates;
}

export async function startDetection(body: DetectionRequest): Promise<DetectionRun> {
  const { data } = await api.post<DetectionRun>('/api/v1/factors/detections', body);
  return data;
}

export async function getDetection(runId: string): Promise<DetectionRun> {
  const { data } = await api.get<DetectionRun>(`/api/v1/factors/detections/${runId}`);
  return data;
}

/** A run is settled when the miner can say nothing more about it. */
export function isRunSettled(run: DetectionRun | undefined): boolean {
  return run?.status === 'done' || run?.status === 'failed';
}

// ── Library ──────────────────────────────────────────────────────────────────
//
// A factor is kept, so these shapes outlive a page view. Two of them are worth
// naming: `evaluation.state` is the *row's* account of whether a run is going,
// finished, failed or lost (the server resolves it, so a worker that died
// mid-evaluation reads as `lost` rather than as a spinner forever), and the
// tearsheet is stored verbatim from the miner — the charts read it as-is.

export type FactorStatus = 'candidate' | 'promoted' | 'rejected';
export type FactorSource = 'user' | 'agent' | 'sota' | 'athena';
export type EvaluationDataset = 'debug' | 'full';
export type EvaluationPhase = 'none' | 'running' | 'done' | 'failed' | 'lost';

export interface EvaluationState {
  state: EvaluationPhase;
  dataset?: EvaluationDataset;
  window_days?: number | null;
  quantiles?: number | null;
  periods?: number[] | null;
  n_dates?: number | null;
  n_symbols?: number | null;
  eval_window?: { start?: string; end?: string } | null;
  hypothesis_missing?: boolean;
  started_at?: string;
  finished_at?: string;
  error?: string;
  error_kind?: string;
}

/** Per-forward-period quantile means (Q1..Qn) — the monotonicity evidence. */
export interface QuantileReturns {
  mean_period_return?: Record<string, number | null>;
  annualized?: Record<string, number | null>;
}

export interface LongShortSpread {
  mean_period_spread?: number | null;
  annualized?: number | null;
}

export interface IcStats {
  period?: string;
  mean?: number | null;
  std?: number | null;
  ir?: number | null;
  series_summary?: { days?: number; positive_ratio?: number | null };
  decay?: Record<string, number | null>;
}

export interface TearSheet {
  quantile_returns?: Record<string, QuantileReturns>;
  long_short?: Record<string, LongShortSpread>;
  ic?: IcStats;
  turnover?: { top?: number | null; bottom?: number | null };
  method?: string;
  n_days?: number;
  n_symbols?: number;
}

export interface MonotonicityReport {
  rho?: number | null;
  direction?: 'increasing' | 'decreasing' | 'non_monotonic' | 'unknown';
  monotonic?: boolean | null;
  values?: number[] | null;
}

export interface FactorLibrarySummary {
  factor_id: string;
  name: string;
  hypothesis: string;
  description: string;
  source: FactorSource | string;
  status: FactorStatus | string;
  code_hash: string;
  ic: number | null;
  ir: number | null;
  t_stat: number | null;
  ic_half_life_days: number | null;
  monotonicity: Record<string, MonotonicityReport>;
  evaluation: EvaluationState;
  last_evaluated_at: string | null;
  promoted_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface FactorLibraryItem extends FactorLibrarySummary {
  code: string;
  formulation: string;
  variables: Record<string, unknown>;
  metrics: {
    tearsheet?: TearSheet;
    ic?: number | null;
    ir?: number | null;
    t_stat?: number | null;
    ic_half_life_days?: number | null;
    monotonicity?: Record<string, MonotonicityReport>;
    evaluation?: EvaluationState;
  };
}

export interface FactorLibraryCounts {
  total?: number;
  candidate?: number;
  promoted?: number;
  rejected?: number;
  evaluated?: number;
}

export interface FactorLibraryList {
  factors: FactorLibrarySummary[];
  counts: FactorLibraryCounts;
}

export interface FactorLibraryFilters {
  status?: FactorStatus | null;
  source?: FactorSource | null;
  q?: string;
}

export interface SaveFactorRequest {
  name: string;
  hypothesis: string;
  code: string;
  description?: string;
  formulation?: string;
  source?: FactorSource;
}

export interface EvaluateFactorRequest {
  dataset?: EvaluationDataset;
  quantiles?: number;
  periods?: number[];
  window_days?: number;
}

/** Stable key for a filter set — the list query is cached per set. */
export function libraryFilterKey(filters: FactorLibraryFilters): string {
  return [filters.status ?? '', filters.source ?? '', filters.q ?? ''].join('|');
}

export async function listFactorLibrary(
  filters: FactorLibraryFilters = {},
): Promise<FactorLibraryList> {
  const { data } = await api.get<FactorLibraryList>('/api/v1/factors/library', {
    params: {
      status: filters.status || undefined,
      source: filters.source || undefined,
      q: filters.q || undefined,
    },
  });
  return data;
}

export async function getFactorLibraryItem(factorId: string): Promise<FactorLibraryItem> {
  const { data } = await api.get<FactorLibraryItem>(`/api/v1/factors/library/${factorId}`);
  return data;
}

export async function saveFactorLibraryItem(
  body: SaveFactorRequest,
): Promise<FactorLibraryItem> {
  const { data } = await api.post<FactorLibraryItem>('/api/v1/factors/library', body);
  return data;
}

export async function deleteFactorLibraryItem(factorId: string): Promise<void> {
  await api.delete(`/api/v1/factors/library/${factorId}`);
}

export async function setFactorLibraryStatus(
  factorId: string,
  status: FactorStatus,
): Promise<FactorLibraryItem> {
  const { data } = await api.post<FactorLibraryItem>(
    `/api/v1/factors/library/${factorId}/status`,
    { status },
  );
  return data;
}

export async function evaluateFactorLibraryItem(
  factorId: string,
  body: EvaluateFactorRequest = {},
): Promise<FactorLibraryItem> {
  const { data } = await api.post<FactorLibraryItem>(
    `/api/v1/factors/library/${factorId}/evaluate`,
    body,
  );
  return data;
}

/** An evaluation is still moving while the row says so (and only then). */
export function isEvaluationRunning(item: FactorLibraryItem | undefined): boolean {
  return item?.evaluation?.state === 'running';
}
