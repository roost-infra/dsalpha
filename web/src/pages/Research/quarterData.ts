import { api } from '@/api/client';

export interface Filing {
  end: string;
  filed: string;
  accession: string;
  form: string;
  url: string;
}

export interface Fact extends Filing {
  tag: string;
  start: string;
  value: number;
  sign: 1 | -1;
}

export interface Observation {
  value: number;
  method: 'reported' | 'difference';
  evidence: Fact[];
}

export interface Metric {
  key: 'revenue' | 'operating_income' | 'net_income' | 'operating_cash_flow';
  current: Observation;
  previous: Observation | null;
  year_ago: Observation | null;
  qoq: number | null;
  yoy: number | null;
}

export interface Quarter {
  symbol: string;
  company: string;
  currency: string;
  fetched_at: string;
  stale?: boolean;
  selected: Filing;
  periods: Filing[];
  metrics: Metric[];
}

export async function getQuarter(symbol: string, period: string | null, signal: AbortSignal) {
  const { data } = await api.get<Quarter>(`/api/v1/research/quarter/${encodeURIComponent(symbol)}`, {
    signal,
    params: period ? { period } : undefined,
    timeout: 30_000,
  });
  return data;
}
