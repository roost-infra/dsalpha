import { useMemo } from 'react';
import { NAV_ITEMS, type NavItem } from './navItems';
import { PAGE_PLUGINS } from '@/plugins/registry';
import { usePagePlugins } from '@/plugins/usePagePlugins';

/**
 * The primary nav items this user can see, in NAV_ITEMS order.
 *
 * Orders is offered when a broker is connected or the ledger holds an order
 * from before; someone with neither is spared an entry into an empty list.
 * A gated item is drawn only on a settled `true`, so the loading answer hides
 * it: an entry that appears a beat after the shell has painted reads as the
 * app changing its mind, and the route behind it is reachable by URL anyway.
 */
export function useNavItems(): NavItem[] {
  const { enabled } = usePagePlugins();
  return useMemo(() => {
    const core = NAV_ITEMS;
    const pluginItems: NavItem[] = PAGE_PLUGINS.filter((plugin) => enabled.has(plugin.id)).flatMap(
      (plugin) =>
        plugin.pages.map((page) => ({
          key: page.path,
          icon: plugin.icon,
          labelKey: page.labelKey,
          match: 'exact-or-sub' as const,
          surface: 'plugin' as const,
        })),
    );
    return [...core, ...pluginItems];
  }, [enabled]);
}
