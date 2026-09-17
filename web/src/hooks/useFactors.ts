/**
 * Factor Board queries.
 *
 * The polling cadence is the whole design here: a detection runs for minutes, and
 * two things must stay true — the progress list has to move while it runs, and
 * the page must go quiet once it settles. React Query's `refetchInterval` reads
 * the last fetched data, so the interval is derived from the run's own status
 * rather than from an effect that has to be torn down on unmount.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';

import {
  getDetection,
  getFactorMinerHealth,
  getFactorTemplates,
  isRunSettled,
  startDetection,
  type DetectionRequest,
  type DetectionRun,
} from '@/api/factors';
import { queryKeys } from '@/lib/queryKeys';

/**
 * The server's own explanation for a rejected detection.
 *
 * Every failure the router can produce carries `{message, kind}` in `detail`, and
 * that sentence names the thing to fix ("factor-miner rejected the credential")
 * where axios would only say "Request failed with status code 401". The client's
 * response interceptor already lifts `detail.message` onto `error.message` for
 * these shapes, so this only has to fall back when it did not.
 */
export function detectionErrorMessage(error: unknown): string {
  if (!error) return '';
  const axiosError = error as AxiosError<{ detail?: unknown }>;
  const detail = axiosError.response?.data?.detail;
  if (detail && typeof detail === 'object' && typeof (detail as { message?: string }).message === 'string') {
    return (detail as { message: string }).message;
  }
  if (typeof detail === 'string') return detail;
  return error instanceof Error ? error.message : '检测请求失败';
}

/** Fast enough that a stage transition lands while the reader is watching, slow
 *  enough that a four-minute run is ~80 requests instead of thousands. */
const DETECTION_POLL_MS = 3_000;

/**
 * A refusal the run id will keep getting, however often it is asked.
 *
 * 404 is no such run — the ledger is process-local and expires, so this is the
 * normal outcome after a backend restart, and it is also what the submit path's
 * own 503/401 family is not. Modelled on `isDefinitiveOrderError`
 * (hooks/useOrders.ts), for the same reason: a poll aimed at an id the server
 * cannot answer must stop, not spin.
 */
export function isDefinitiveDetectionError(error: unknown): boolean {
  const status = (error as { response?: { status?: number } } | null)?.response?.status;
  return status === 404;
}

export function useFactorMinerHealth() {
  return useQuery({
    queryKey: queryKeys.factors.health(),
    queryFn: getFactorMinerHealth,
    // The reachability of a service is not a fact that changes on a clock: it is
    // a property of the deployment, and a retry belongs to the moment the reader
    // acts on it (a submit reports its own failure). A short staleTime here just
    // means a down service is re-probed and re-failed every minute for as long as
    // the page is open.
    staleTime: Infinity,
  });
}

export function useFactorTemplates() {
  return useQuery({
    queryKey: queryKeys.factors.templates(),
    queryFn: getFactorTemplates,
    // Starter scripts ship with the server; they change only on deploy.
    staleTime: Infinity,
  });
}

/**
 * One detection, polled until it settles.
 *
 * A 404 is expected rather than exceptional: run state is process-local and
 * expires, so a page holding an id across a backend restart must find out. That
 * case stops the poll — the id will never resolve — and surfaces as an error for
 * the page to explain. Any other failure is read as a bad moment and polled
 * through, because a detection that is still advancing server-side should not be
 * abandoned by the client.
 */
export function useDetection(runId: string | null) {
  return useQuery({
    queryKey: queryKeys.factors.detection(runId ?? ''),
    queryFn: () => getDetection(runId as string),
    enabled: !!runId,
    retry: false,
    refetchInterval: (query) => {
      // The error is checked before the data, and that order is the whole fix.
      // A failed refetch leaves the *previous* data in place, so the seeded
      // (queued) copy is still sitting in `query.state.data` after a 404 — an
      // `if (!data)` guard never fires, the stale run reads as unsettled, and an
      // id the server has forgotten is re-requested every 3s forever. (Pinned by
      // `__tests__/useFactors.polling.test.tsx`, which failed against the
      // data-first version.)
      if (isDefinitiveDetectionError(query.state.error)) return false;
      const run = query.state.data as DetectionRun | undefined;
      return isRunSettled(run) ? false : DETECTION_POLL_MS;
    },
  });
}

/**
 * Submit a detection.
 *
 * The response is a run in `queued`, not a result, so the mutation seeds the
 * detection cache with it — that write is what flips the page from "start" to
 * "running" without a second round trip, and it is the id the poll then follows.
 */
export function useStartDetection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DetectionRequest) => startDetection(body),
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.factors.detection(run.run_id), run);
      queryClient.invalidateQueries({ queryKey: queryKeys.factors.detections() });
    },
  });
}
