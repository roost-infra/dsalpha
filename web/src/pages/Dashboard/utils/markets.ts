/**
 * The dashboard's market regions: which indices the tape shows, which symbols a
 * fresh card seeds, and which venue a symbol belongs to.
 *
 * The backend serves both regions from the same endpoints — a CN listing is a
 * suffixed symbol (`600519.SH`, `000001.SH`) and routes through the market
 * protocol to its own quote source — so the only thing a dashboard needs is a
 * choice of *what to show*. That choice lives here rather than in the widget
 * code, so the overview card, the mini-chart grid and the header switch all
 * read one list.
 *
 * US indices keep the legacy bare spellings (`GSPC`, not `^GSPC`): the
 * snapshot route normalizes the caret away, and the bare form is what the
 * existing cache keys use. CN indices are venue-listed and must keep their
 * suffix — `000001.SH` is the Shanghai Composite, while a bare `000001` is the
 * Shenzhen listing of Ping An Bank.
 *
 * @module pages/Dashboard/utils/markets
 */

import { DEFAULT_BLUE_CHIPS } from '../widgets/framework/defaults'

/** The regions the dashboard can show. */
export type DashboardMarket = 'us' | 'cn'

/** Every region, in the order the header switch draws them. */
export const DASHBOARD_MARKETS: readonly DashboardMarket[] = ['cn', 'us']

/**
 * What a dashboard shows before the reader picks a region.
 *
 * A-shares, not US: the product's readers are A-share first, and a fresh
 * dashboard whose tape opens on the S&P is the complaint this switch answers.
 * A reader who wants the US row picks it once and it is saved.
 */
export const DEFAULT_DASHBOARD_MARKET: DashboardMarket = 'cn'

/** Whether an arbitrary stored value names a supported region. */
export function isDashboardMarket(value: unknown): value is DashboardMarket {
  return value === 'us' || value === 'cn'
}

/** One index tile: the wire symbol and its name in each shipped locale. */
export interface MarketIndexSpec {
  /** Wire spelling: bare for a US family index, venue-suffixed for a CN one. */
  code: string
  /** Name for the zh-CN UI. */
  nameZh: string
  /** Name for the en-US UI. */
  nameEn: string
}

/**
 * The index row each region shows, in tile order.
 *
 * Five tiles is the row width the overview card is designed for; a region with
 * a sixth entry would wrap. The CN row is the four broad gauges A-share readers
 * expect plus the STAR board, mirroring the US row's three broad gauges plus
 * small caps and volatility.
 */
export const MARKET_INDEX_CATALOG: Record<DashboardMarket, readonly MarketIndexSpec[]> = {
  us: [
    { code: 'GSPC', nameZh: '标普 500', nameEn: 'S&P 500' },
    { code: 'IXIC', nameZh: '纳斯达克', nameEn: 'NASDAQ' },
    { code: 'DJI', nameZh: '道琼斯', nameEn: 'Dow Jones' },
    { code: 'RUT', nameZh: '罗素 2000', nameEn: 'Russell 2000' },
    { code: 'VIX', nameZh: 'VIX', nameEn: 'VIX' },
  ],
  cn: [
    { code: '000001.SH', nameZh: '上证指数', nameEn: 'SSE Composite' },
    { code: '399001.SZ', nameZh: '深证成指', nameEn: 'SZSE Component' },
    { code: '399006.SZ', nameZh: '创业板指', nameEn: 'ChiNext' },
    { code: '000300.SH', nameZh: '沪深300', nameEn: 'CSI 300' },
    { code: '000688.SH', nameZh: '科创50', nameEn: 'STAR 50' },
  ],
}

/** The wire symbols of one region's index row. */
export function marketIndexSymbols(market: DashboardMarket): string[] {
  return MARKET_INDEX_CATALOG[market].map((spec) => spec.code)
}

/** The name of *code* in the UI's language, or the symbol when it is not a catalog index. */
export function marketIndexName(code: string, locale: string | null | undefined): string | undefined {
  const spec = [...MARKET_INDEX_CATALOG.us, ...MARKET_INDEX_CATALOG.cn].find((item) => item.code === code)
  if (spec === undefined) return undefined
  return (locale ?? '').toLowerCase().startsWith('zh') ? spec.nameZh : spec.nameEn
}

/** The symbols a fresh card seeds when the reader has not chosen any. */
export function marketBlueChips(market: DashboardMarket): string[] {
  return market === 'cn' ? [...CN_BLUE_CHIPS] : [...DEFAULT_BLUE_CHIPS]
}

/**
 * A-share seed row for a fresh card: the Kweichow Moutai / Wuliangye consumer
 * pair, CATL and BYD in new energy, Ping An Bank and China Merchants Bank.
 * Suffixed, because a bare six-digit code is ambiguous between Shanghai and
 * Shenzhen.
 */
const CN_BLUE_CHIPS: readonly string[] = [
  '600519.SH',
  '000858.SZ',
  '300750.SZ',
  '002594.SZ',
  '000001.SZ',
  '600036.SH',
]

const CN_SUFFIX = /\.(SH|SZ|BJ|SS)$/i

/** Whether a symbol lists on a mainland-exchange venue. */
export function isCnSymbol(symbol: string): boolean {
  return CN_SUFFIX.test(symbol.trim())
}

/** The venue timezone a symbol's clock belongs to. */
export function venueTimeZoneForSymbol(symbol: string): string {
  return isCnSymbol(symbol) ? 'Asia/Shanghai' : 'America/New_York'
}

/** The region a symbol belongs to; a bare ticker reads as US. */
export function marketOfSymbol(symbol: string): DashboardMarket {
  return isCnSymbol(symbol) ? 'cn' : 'us'
}
