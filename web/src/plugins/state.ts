import { useSyncExternalStore } from 'react';

/**
 * A tiny app-wide mirror of the enabled page-plugin ids. Several surfaces
 * (onboarding tasks, dashboard contributions) need the answer but are not
 * always under a QueryClient, so the hook that owns the query publishes here
 * and readers subscribe without their own fetch.
 */
let enabledIds: ReadonlySet<string> = new Set();
const listeners = new Set<() => void>();

export function setEnabledPagePlugins(next: ReadonlySet<string>): void {
  const same =
    next.size === enabledIds.size && [...next].every((id) => enabledIds.has(id));
  if (same) return;
  enabledIds = next;
  for (const listener of listeners) listener();
}

export function getEnabledPagePlugins(): ReadonlySet<string> {
  return enabledIds;
}

export function useEnabledPagePlugins(): ReadonlySet<string> {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getEnabledPagePlugins,
    getEnabledPagePlugins,
  );
}
