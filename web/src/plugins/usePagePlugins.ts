import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getPagePlugins, setPagePlugin, type PagePluginList } from './api';
import { PAGE_PLUGINS } from './registry';

const KEY = ['page-plugins'] as const;

export function usePagePlugins() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: KEY, queryFn: getPagePlugins });
  const states = query.data?.plugins ?? [];
  const enabled = new Set(states.filter((s) => s.enabled).map((s) => s.plugin_id));
  const toggle = useMutation({
    mutationFn: ({ pluginId, enabled }: { pluginId: string; enabled: boolean }) =>
      setPagePlugin(pluginId, enabled),
    onSuccess: (next) => {
      queryClient.setQueryData<PagePluginList>(KEY, (current) => ({
        plugins: (current?.plugins ?? []).map((plugin) =>
          plugin.plugin_id === next.plugin_id ? next : plugin,
        ),
      }));
      void queryClient.invalidateQueries({ queryKey: KEY });
    },
  });
  return {
    plugins: PAGE_PLUGINS,
    states,
    enabled,
    isLoading: query.isLoading,
    isError: query.isError,
    toggle: toggle.mutateAsync,
    isToggling: toggle.isPending,
  };
}
