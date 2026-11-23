/**
 * The built-in Bot market, v1: browse and install only.
 *
 * Every template here ships with the platform; there is no publishing, no
 * pricing and no admin surface. An install copies a template's persona, tools
 * and skills into a brand new bot in a workspace the installer picks, which is
 * why the install body names a workspace and a bot name rather than a listing
 * id alone.
 *
 * The four endpoints live under `/api/v1/market`, deliberately apart from the
 * older read-only `/api/v1/marketplace` plugin catalog.
 */
import { api } from '@/api/client';

/** One filter chip. `id` is what the API takes, `label` is what the reader sees. */
export interface MarketCategory {
  id: string;
  label: string;
}

/** A bot as the grid draws it: no persona, no tools, no installs. */
export interface MarketBotCard {
  slug: string;
  name: string;
  /** The catalogue's emoji, shown as the card's face. */
  icon?: string;
  summary: string;
  category: string;
  tags: string[];
  version: string;
  featured: boolean;
  /** The caller already has at least one install of this template. */
  installed: boolean;
}

/** `GET /api/v1/market/bots?q=&category=`. */
export interface MarketBotListResponse {
  bots: MarketBotCard[];
  categories: MarketCategory[];
}

/** One workspace a template has already been installed into. */
export interface MarketBotInstallRef {
  workspace_id: string;
  workspace_name: string;
  bot_id: string;
}

/** `GET /api/v1/market/bots/{slug}`: everything the detail view shows. */
export interface MarketBotDetail {
  slug: string;
  name: string;
  icon?: string;
  summary: string;
  description: string;
  category: string;
  tags: string[];
  version: string;
  featured: boolean;
  persona: string;
  tools: string[];
  skills: string[];
  installs: MarketBotInstallRef[];
}

/** The body of `POST /api/v1/market/bots/{slug}/install`. */
export interface MarketInstallInput {
  workspace_id: string;
  name: string;
}

/** The 201 answer of an install. */
export interface MarketInstallResult {
  install_id: string;
  bot: {
    bot_id: string;
    name: string;
    workspace_id: string;
  };
}

/** One row of `GET /api/v1/market/me/installs`. */
export interface MarketInstall {
  install_id: string;
  slug: string;
  name: string;
  version: string;
  workspace_id: string;
  workspace_name: string;
  bot_id: string;
  created_at: string;
}

/** `GET /api/v1/market/me/installs`. */
export interface MarketInstallsResponse {
  installs: MarketInstall[];
}

/** The market's query keys. A write invalidates `all`, which refreshes the
 *  grids, any open detail (its installed spots) and the installed tab together. */
export const storeKeys = {
  all: ['market'] as const,
  bots: (q: string, category: string | null) =>
    [...storeKeys.all, 'bots', { q, category }] as const,
  bot: (slug: string) => [...storeKeys.all, 'bot', slug] as const,
  installs: () => [...storeKeys.all, 'installs'] as const,
};

/** The template list. Blank filters are left out of the URL rather than sent as
 *  empty strings, so "no search" is the unfiltered list on the server too. */
export async function listMarketBots({
  q = '',
  category = null,
}: {
  q?: string;
  category?: string | null;
} = {}): Promise<MarketBotListResponse> {
  const params: Record<string, string> = {};
  const query = q.trim();
  if (query) params.q = query;
  if (category) params.category = category;
  const { data } = await api.get<MarketBotListResponse>(
    '/api/v1/market/bots',
    Object.keys(params).length > 0 ? { params } : undefined,
  );
  return data;
}

export async function getMarketBot(slug: string): Promise<MarketBotDetail> {
  const { data } = await api.get<MarketBotDetail>(
    `/api/v1/market/bots/${encodeURIComponent(slug)}`,
  );
  return data;
}

/**
 * Copy a template into a new bot. The server answers 400 for Home, 409 for a
 * name in use or a workspace at its bot cap, and 404 for an unknown slug; each
 * carries a readable `detail` that the form shows as-is.
 */
export async function installMarketBot(
  slug: string,
  input: MarketInstallInput,
): Promise<MarketInstallResult> {
  const { data } = await api.post<MarketInstallResult>(
    `/api/v1/market/bots/${encodeURIComponent(slug)}/install`,
    input,
  );
  return data;
}

export async function getMyMarketInstalls(): Promise<MarketInstallsResponse> {
  const { data } = await api.get<MarketInstallsResponse>('/api/v1/market/me/installs');
  return data;
}
