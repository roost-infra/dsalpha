/**
 * React Query bindings for the built-in Bot market.
 *
 * The list and installed reads follow the app's usual shape: a query key from
 * the page's own factory, a 30s stale window, and `keepPreviousData` so
 * changing a filter holds the grid on screen instead of flashing a skeleton.
 * The install mutation invalidates the whole market family, which refreshes
 * the "Installed" badges on every card, any open detail and the Installed tab.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getMarketBot,
  getMyMarketInstalls,
  installMarketBot,
  listMarketBots,
  storeKeys,
  type MarketInstallInput,
} from './api';

export function useMarketBots(q: string, category: string | null) {
  return useQuery({
    queryKey: storeKeys.bots(q, category),
    queryFn: () => listMarketBots({ q, category }),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

/** One template's full detail. Disabled while no card is open. */
export function useMarketBot(slug: string | null) {
  return useQuery({
    queryKey: storeKeys.bot(slug ?? ''),
    queryFn: () => getMarketBot(slug!),
    enabled: !!slug,
    staleTime: 30_000,
  });
}

/** The caller's installs. Kept off until the Installed tab is the one showing. */
export function useMyMarketInstalls(enabled: boolean) {
  return useQuery({
    queryKey: storeKeys.installs(),
    queryFn: () => getMyMarketInstalls(),
    enabled,
    staleTime: 30_000,
  });
}

export function useInstallMarketBot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, input }: { slug: string; input: MarketInstallInput }) =>
      installMarketBot(slug, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: storeKeys.all });
    },
  });
}
