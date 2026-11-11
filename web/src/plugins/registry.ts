import { lazy } from 'react';
import { CandlestickChart } from 'lucide-react';
import type { PagePlugin } from './types';

/**
 * The built-in page plugins this build ships. A plugin is compiled into the
 * bundle; the server stores only whether the user enabled it. There is no
 * remote plugin loading, so this list is the complete page-plugin surface.
 */
export const PAGE_PLUGINS: PagePlugin[] = [
  {
    id: 'market-center',
    nameKey: 'plugins.builtin.marketCenter.name',
    descriptionKey: 'plugins.builtin.marketCenter.description',
    icon: CandlestickChart,
    defaultEnabled: false,
    pages: [
      {
        id: 'market',
        path: '/p/market',
        labelKey: 'plugins.builtin.marketCenter.name',
        component: lazy(() => import('@/pages/MarketView/MarketView')),
      },
    ],
  },
];

export const PAGE_PLUGINS_BY_ID = new Map(PAGE_PLUGINS.map((plugin) => [plugin.id, plugin]));

export function pagePluginById(id: string): PagePlugin | null {
  return PAGE_PLUGINS_BY_ID.get(id) ?? null;
}
