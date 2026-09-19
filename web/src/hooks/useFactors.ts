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
  deleteFactorLibraryItem,
  evaluateFactorLibraryItem,
  getDetection,
  getFactorLibraryItem,
  getFactorMinerHealth,
  getFactorTemplates,
  isEvaluationRunning,
  isRunSettled,
  libraryFilterKey,
  listFactorLibrary,
  saveFactorLibraryItem,
  setFactorLibraryStatus,
  startDetection,
  type DetectionRequest,
  type DetectionRun,
  type EvaluateFactorRequest,
  type FactorLibraryFilters,
  type FactorStatus,
  type SaveFactorRequest,
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

/** The same cadence for an evaluation: the miner answers in ~40s on the debug
 *  panel and a couple of minutes on the full one, so a poll per few seconds is
 *  what makes the difference between "it is done" and "it is still going"
 *  visible without hammering a service that is busy running the job. */
const LIBRARY_POLL_MS = 4_000;

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

// ── Library ──────────────────────────────────────────────────────────────────
//
// Every write invalidates the `library()` prefix rather than the exact keys it
// touched: a save can create a row, change a row's status, or clear its metrics
// (an edited code invalidates the old evaluation), and the open detail panel and
// the filtered list both have to reflect whichever of those happened. Naming the
// prefix is what keeps the writer from having to know.

/** The library table for one filter set. */
export function useFactorLibrary(filters: FactorLibraryFilters = {}) {
  return useQuery({
    queryKey: queryKeys.factors.libraryList(libraryFilterKey(filters)),
    queryFn: () => listFactorLibrary(filters),
    // A factor's metrics change only when someone evaluates it, and that path
    // invalidates this key itself. Re-fetching on every mount would ask the
    // database a question nobody changed the answer to.
    staleTime: 30_000,
  });
}

/**
 * One factor, polled only while its evaluation runs.
 *
 * The state comes from the row, not from this client, so a page reload, a second
 * device or a different worker all agree. Once the row settles the poll stops —
 * leasing a *lost* state (the worker went away) means the poll could otherwise
 * spin forever on a run nothing is advancing.
 */
export function useFactorLibraryItem(factorId: string | null) {
  return useQuery({
    queryKey: queryKeys.factors.libraryItem(factorId ?? ''),
    queryFn: () => getFactorLibraryItem(factorId as string),
    enabled: !!factorId,
    retry: false,
    refetchInterval: (query) =>
      isEvaluationRunning(query.state.data) ? LIBRARY_POLL_MS : false,
  });
}

export function useSaveFactor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SaveFactorRequest) => saveFactorLibraryItem(body),
    onSuccess: (item) => {
      queryClient.setQueryData(queryKeys.factors.libraryItem(item.factor_id), item);
      queryClient.invalidateQueries({ queryKey: queryKeys.factors.library() });
    },
  });
}

export function useDeleteFactor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (factorId: string) => deleteFactorLibraryItem(factorId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.factors.library() });
    },
  });
}

export function useSetFactorStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ factorId, status }: { factorId: string; status: FactorStatus }) =>
      setFactorLibraryStatus(factorId, status),
    onSuccess: (item) => {
      queryClient.setQueryData(queryKeys.factors.libraryItem(item.factor_id), item);
      queryClient.invalidateQueries({ queryKey: queryKeys.factors.library() });
    },
  });
}

/**
 * Start an evaluation.
 *
 * The 202's body is the row already in `running`, so the cache is seeded with it:
 * that write is what switches the panel from the button to the live state without
 * a second round trip, and the item query's poll interval then follows it to a
 * terminal state on its own.
 */
export function useEvaluateFactor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      factorId,
      body,
    }: {
      factorId: string;
      body?: EvaluateFactorRequest;
    }) => evaluateFactorLibraryItem(factorId, body ?? {}),
    onSuccess: (item) => {
      queryClient.setQueryData(queryKeys.factors.libraryItem(item.factor_id), item);
      queryClient.invalidateQueries({ queryKey: queryKeys.factors.library() });
    },
  });
}
