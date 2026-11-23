import type { ComputerPlatform } from '@/types/api';

export const PLATFORM_NAMES: Record<ComputerPlatform, string> = {
  linux: 'Linux',
  macos: 'macOS',
  windows: 'Windows',
};

export function desktopPath(computerId: string, workspaceId?: string) {
  const path = `/computers/${encodeURIComponent(computerId)}/desktop`;
  return workspaceId ? `${path}?${new URLSearchParams({ workspace: workspaceId })}` : path;
}

export const workspaceFilesPath = (workspaceId: string) => `/chat/${encodeURIComponent(workspaceId)}?panel=files`;
