import { api } from '@/api/client';

export interface PagePluginState {
  plugin_id: string;
  enabled: boolean;
}

export interface PagePluginList {
  plugins: PagePluginState[];
}

export async function getPagePlugins(): Promise<PagePluginList> {
  const { data } = await api.get<PagePluginList>('/api/v1/page-plugins');
  return data;
}

export async function setPagePlugin(pluginId: string, enabled: boolean): Promise<PagePluginState> {
  const { data } = await api.patch<PagePluginState>(
    `/api/v1/page-plugins/${encodeURIComponent(pluginId)}`,
    { enabled },
  );
  return data;
}
