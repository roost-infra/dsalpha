import { lazyWithMotion } from '@/lib/lazyWithMotion';
import { CandlestickChart, NotebookPen } from 'lucide-react';
import type { PagePlugin, PagePluginPage } from './types';

/**
 * The built-in page plugins this build ships. A plugin is compiled into the
 * bundle; the server stores only whether the user enabled it. There is no
 * remote plugin loading, so this list is the complete page-plugin surface.
 */
export const PAGE_PLUGINS: PagePlugin[] = [
  {
    id: 'content-desk',
    nameKey: 'plugins.builtin.contentDesk.name',
    descriptionKey: 'plugins.builtin.contentDesk.description',
    icon: NotebookPen,
    defaultEnabled: false,
    pages: [
      {
        id: 'content-desk',
        path: '/p/content-desk',
        labelKey: 'plugins.builtin.contentDesk.name',
        component: lazyWithMotion(() => import('@/pages/ContentDesk/ContentDesk')),
      },
    ],
  },
  {
    id: 'market-center',
    nameKey: 'plugins.builtin.marketCenter.name',
    descriptionKey: 'plugins.builtin.marketCenter.description',
    icon: CandlestickChart,
    defaultEnabled: false,
    dashboard: { presetId: 'morning-brief' },
    pages: [
      {
        id: 'market',
        path: '/p/market',
        labelKey: 'plugins.builtin.marketCenter.name',
        component: lazyWithMotion(() => import('@/pages/MarketView/MarketView')),
      },
    ],
  },
];

export const PAGE_PLUGINS_BY_ID = new Map(PAGE_PLUGINS.map((plugin) => [plugin.id, plugin]));

export function pagePluginById(id: string): PagePlugin | null {
  return PAGE_PLUGINS_BY_ID.get(id) ?? null;
}

/** Resolve `/p/:routeId`: plugin id first, then a page id/path inside one. */
export function pagePluginForRoute(routeId: string): PagePlugin | null {
  return pluginPageForRoute(routeId)?.plugin ?? null;
}

export interface ResolvedPluginPage {
  plugin: PagePlugin;
  page: PagePluginPage;
}

/**
 * Resolve a `/p/:routeId` segment to both the plugin and the concrete page.
 * `routeId` is normally a page id (`market`), but a plugin id is accepted and
 * normalized to the plugin's first page by the host. Keeping the page in the
 * result is what lets multi-page plugins render the page the URL names.
 */
export function pluginPageForRoute(routeId: string): ResolvedPluginPage | null {
  for (const plugin of PAGE_PLUGINS) {
    const page = plugin.pages.find(
      (candidate) =>
        candidate.id === routeId || candidate.path === `/p/${routeId}`,
    );
    if (page) return { plugin, page };
  }
  const direct = pagePluginById(routeId);
  return direct?.pages[0] ? { plugin: direct, page: direct.pages[0] } : null;
}
