// The market-center page plugin's dashboard contribution. It stays a separate
// module so the plugin owns its widgets and the dashboard can decide whether
// to register them; today the module is bundled statically, and moving it to a
// dynamic import only changes the chunk boundary.
import './definitions/MarketsOverviewWidget';
import './definitions/InsightBriefWidget';
import './definitions/NewsFeedWidget';
import './definitions/EarningsCalendarWidget';
import './definitions/WatchlistWidget';
import './definitions/PortfolioWidget';
import './definitions/PortfolioWatchlistWidget';
import './definitions/MiniChartGridWidget';
import './definitions/ChartWidget.register';
import './definitions/tv/TickerTapeWidget';
import './definitions/tv/StockHeatmapWidget';
import './definitions/tv/CryptoHeatmapWidget';
import './definitions/tv/ForexHeatmapWidget';
import './definitions/tv/ETFHeatmapWidget';
import './definitions/tv/EconomicEventsWidget';
import './definitions/tv/EconomicMapWidget';
import './definitions/tv/TechnicalsWidget';
import './definitions/tv/MoversWidget';
import './definitions/tv/SymbolSpotlightWidget';
import './definitions/tv/SingleTickerWidget';
import './definitions/tv/SymbolInfoWidget';
import './definitions/tv/CompanyProfileWidget';
import './definitions/tv/CompanyFinancialsWidget';
import './definitions/tv/StockScreenerWidget';
import './definitions/tv/CryptoScreenerWidget';
import './definitions/tv/TopStoriesWidget';
import { listWidgets, setWidgetPlugin } from './framework/WidgetRegistry';

/** Financial widgets owned by the market-center plugin. */
export const MARKET_WIDGET_TYPES = [
  'markets.overview',
  'insight.brief',
  'news.feed',
  'calendar.earnings',
  'watchlist.list',
  'portfolio.holdings',
  'personal.portfolioWatchlist',
  'markets.miniChartGrid',
  'chart.symbol',
] as const;

export const MARKET_WIDGET_PREFIXES = ['tv.'] as const;

export function registerMarketDashboard(): void {
  setWidgetPlugin(MARKET_WIDGET_TYPES, 'market-center');
  // TV widgets have stable type prefixes, so the contribution does not have
  // to mirror 20 type literals that already live with their definitions.
  for (const def of listWidgets()) {
    if (MARKET_WIDGET_PREFIXES.some((prefix) => def.type.startsWith(prefix))) {
      setWidgetPlugin([def.type], 'market-center');
    }
  }
}

registerMarketDashboard();
