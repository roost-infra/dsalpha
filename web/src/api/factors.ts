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

/** One trailing-window cross-sectional IC probe. */
export interface IcProbe {
  window: number;
  ic: number | null;
  days?: number | null;
  error?: string;
}

/** Mining-window vs out-of-sample performance, plus the relative decay. */
export interface OosFinding {
  mining?: Record<string, number | null> | null;
  oos?: Record<string, number | null> | null;
  decay?: number | null;
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
