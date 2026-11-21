import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  clearComposioKey,
  connectConnectedApp,
  connectedAppsKeys,
  disconnectConnectedAccount,
  getConnectedApps,
  saveComposioKey,
} from './api';

export function useConnectedApps() {
  return useQuery({
    queryKey: connectedAppsKeys.all,
    queryFn: getConnectedApps,
    staleTime: 30_000,
  });
}

export function useSaveComposioKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: saveComposioKey,
    onSuccess: (data) => queryClient.setQueryData(connectedAppsKeys.all, data),
  });
}

export function useClearComposioKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: clearComposioKey,
    onSuccess: (data) => queryClient.setQueryData(connectedAppsKeys.all, data),
  });
}

export function useConnectConnectedApp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, alias }: { slug: string; alias?: string }) =>
      connectConnectedApp(slug, alias),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: connectedAppsKeys.all });
    },
  });
}

export function useDisconnectConnectedAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => disconnectConnectedAccount(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: connectedAppsKeys.all });
    },
  });
}
