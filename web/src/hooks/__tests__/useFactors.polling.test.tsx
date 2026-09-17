/**
 * When the detection poll must stop asking.
 *
 * A run id is only answerable while the process that made it still holds it, and
 * the backend defaults to one worker whose ledger expires after an hour — so a
 * page that survives a restart, or sits open past the TTL, is left polling an id
 * that will forever be a 404. The poll reads one predicate for that rather than
 * deciding for itself, and this pins the two halves of the behaviour: the
 * predicate's verdict, and that the hook actually consults it.
 *
 * The bug this locks: `refetchInterval` looked only at `query.state.data`, but a
 * failed refetch leaves the *previous* data in place. A run seeded into the cache
 * by the submit mutation therefore read as "queued" on every failed poll, so an
 * unresolvable id was re-requested every 3s for as long as the tab stayed open —
 * and the page kept showing "detecting" while it did.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { waitFor } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';

import { renderHookWithProviders } from '@/test/utils';

vi.mock('@/api/factors', async () => {
  const actual = await vi.importActual<typeof import('@/api/factors')>('@/api/factors');
  return {
    ...actual,
    getDetection: vi.fn(),
  };
});

import { getDetection } from '@/api/factors';
import { isDefinitiveDetectionError, useDetection } from '../useFactors';

const mockGetDetection = getDetection as unknown as ReturnType<typeof vi.fn>;

function httpError(status: number) {
  return { response: { status } };
}

const queuedRun = {
  run_id: 'abc123',
  name: 'reversal_20',
  status: 'queued' as const,
  current_stage: '',
  created_at: Date.now() / 1000,
  elapsed_sec: 0,
  stages: [],
  findings: {},
  verdict: {},
  error: '',
  error_kind: '',
};

describe('isDefinitiveDetectionError', () => {
  // The ledger is process-local and expires, so the id itself is what is unknown.
  it('stops asking on 404', () => {
    expect(isDefinitiveDetectionError(httpError(404))).toBe(true);
  });

  // The backend had a bad moment, which a later ask can still survive — and the
  // run may well be advancing server-side while the poll fails.
  it.each([500, 502, 503, 429, 408, 401])('keeps asking on %i', (status) => {
    expect(isDefinitiveDetectionError(httpError(status))).toBe(false);
  });

  it('keeps asking when the failure names no status', () => {
    expect(isDefinitiveDetectionError(new Error('Network Error'))).toBe(false);
    expect(isDefinitiveDetectionError(null)).toBe(false);
    expect(isDefinitiveDetectionError(undefined)).toBe(false);
  });
});

describe('useDetection polling', () => {
  let client: QueryClient;

  beforeEach(() => {
    mockGetDetection.mockReset();
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    // Seed exactly what the submit mutation writes: the run as it looked at
    // submit time. This stale copy is what the old interval read as the truth.
    client.setQueryData(['factors', 'detections', 'abc123'], queuedRun);
  });

  // Real timers, not fake ones. The poll interval is a React Query timer, and
  // `waitFor` does not advance fake timers — the two together deadlock. The
  // intervals are short enough (3s) that a real-time wait stays quick.
  it('stops polling a run the server no longer knows', async () => {
    mockGetDetection.mockRejectedValue(httpError(404));

    const { result } = renderHookWithProviders(() => useDetection('abc123'), { queryClient: client });

    await waitFor(() => expect(result.current.isError).toBe(true));
    const afterFirstFetch = mockGetDetection.mock.calls.length;

    await new Promise((resolve) => setTimeout(resolve, 9_500));

    // Three poll intervals of wall clock, and not one further request: the id is
    // definitively unknown, so there is nothing left to ask about.
    expect(mockGetDetection.mock.calls.length).toBe(afterFirstFetch);
  }, 20_000);

  it('keeps polling through a bad moment, because the run may still be advancing', async () => {
    mockGetDetection.mockRejectedValue(httpError(502));

    const { result } = renderHookWithProviders(() => useDetection('abc123'), { queryClient: client });

    await waitFor(() => expect(result.current.isError).toBe(true));
    const afterFirstFetch = mockGetDetection.mock.calls.length;

    await new Promise((resolve) => setTimeout(resolve, 7_000));

    // A 502 is the backend having a bad moment, not the run being gone.
    expect(mockGetDetection.mock.calls.length).toBeGreaterThan(afterFirstFetch);
  }, 20_000);
});
