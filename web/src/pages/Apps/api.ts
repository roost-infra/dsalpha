/**
 * Connected apps: OAuth connections to external apps, proxied through
 * Composio's Tool Router. The server owns the project key and the session; the
 * browser only receives a one-shot authorization link.
 */
import { api } from '@/api/client';

export interface ConnectedAccount {
  id: string;
  alias?: string | null;
  status: string;
}

export interface ConnectedApp {
  slug: string;
  name: string;
  description: string;
  logo?: string | null;
  categories: string[];
  connected: boolean;
  accounts: ConnectedAccount[];
}

export interface ConnectedAppsStatus {
  configured: boolean;
  using_deployment_key: boolean;
  apps: ConnectedApp[];
  error?: string | null;
}

export const connectedAppsKeys = {
  all: ['connected-apps'] as const,
};

export async function getConnectedApps(): Promise<ConnectedAppsStatus> {
  const { data } = await api.get<ConnectedAppsStatus>('/api/v1/connected-apps');
  return data;
}

export async function saveComposioKey(apiKey: string): Promise<ConnectedAppsStatus> {
  const { data } = await api.put<ConnectedAppsStatus>('/api/v1/connected-apps/key', {
    api_key: apiKey,
  });
  return data;
}

export async function clearComposioKey(): Promise<ConnectedAppsStatus> {
  const { data } = await api.delete<ConnectedAppsStatus>('/api/v1/connected-apps/key');
  return data;
}

export async function connectConnectedApp(
  slug: string,
  alias?: string,
): Promise<{ url: string }> {
  const { data } = await api.post<{ url: string }>(
    `/api/v1/connected-apps/${encodeURIComponent(slug)}/connect`,
    { alias: alias || null },
  );
  return data;
}

export async function disconnectConnectedAccount(id: string): Promise<{ ok: boolean }> {
  const { data } = await api.delete<{ ok: boolean }>(
    `/api/v1/connected-apps/accounts/${encodeURIComponent(id)}`,
  );
  return data;
}
