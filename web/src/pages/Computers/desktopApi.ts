import { api } from '@/api/client';
import type { DesktopTransport } from '@/types/api';

export type DesktopRole = 'view' | 'control';

export interface DesktopSession {
  session_id: string;
  ticket: string;
  ws_url: string;
  transport: DesktopTransport;
  role: DesktopRole;
}

const computerPath = (id: string) => `/api/v1/computers/${encodeURIComponent(id)}`;

export async function requestDesktop(id: string, role: DesktopRole, takeover: boolean): Promise<DesktopSession> {
  const path = takeover ? 'takeover' : 'session';
  const { data } = await api.post<DesktopSession>(`${computerPath(id)}/desktop/${path}`, takeover ? null : { role }, {
    timeout: 45_000,
  });
  return data;
}

export async function releaseDesktop(id: string, sessionId: string): Promise<void> {
  await api.delete(`${computerPath(id)}/desktop/session/${encodeURIComponent(sessionId)}`);
}

export async function getDesktopPreview(id: string, signal: AbortSignal): Promise<Blob> {
  const { data } = await api.post<Blob>(`${computerPath(id)}/desktop/screenshot`, null, { responseType: 'blob', signal });
  return data;
}

export async function getSshCommand(id: string) {
  const { data } = await api.get<{ command: string; expires_in_minutes: number | null }>(`${computerPath(id)}/ssh`, {
    timeout: 20_000,
  });
  return data;
}

export function desktopSocketAddress(path: string): string {
  const url = new URL(path, window.location.origin);
  if (url.origin !== window.location.origin) throw new Error('Invalid desktop socket origin');
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.href;
}

export const desktopProtocols = (ticket: string) => ['dsalpha.desktop', ticket];
