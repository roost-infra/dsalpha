/**
 * A-share ETF heatmap: the local counterpart of TradingView's US ETF board.
 *
 * The TV embed only knows US universes (AllUSEtf, EquityEtf, …). When the
 * dashboard is on CN, this board reads the same snapshot quote layer as the
 * watchlist and paints a compact treemap of the main Shanghai/Shenzhen ETFs.
 * China's colour convention applies: red is up, green is down.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader } from '@/components/ui/loader';
import { quoteKey } from '@/lib/quotes/quoteBatcher';
import { useQuotes } from '@/lib/quotes';
import './CnEtfHeatmap.css';

interface EtfRow {
  key: string;
  labelKey: string;
  items: readonly EtfItem[];
}

interface EtfItem {
  symbol: string;
  nameZh: string;
  nameEn: string;
}

/** Liquid, representative A-share ETFs. The wire symbols keep their venue. */
const ROWS: readonly EtfRow[] = [
  {
    key: 'broad',
    labelKey: 'dashboard.widgets.etfHeatmap.cnBroad',
    items: [
      { symbol: '510300.SH', nameZh: '沪深300ETF', nameEn: 'CSI 300 ETF' },
      { symbol: '510500.SH', nameZh: '中证500ETF', nameEn: 'CSI 500 ETF' },
      { symbol: '510050.SH', nameZh: '上证50ETF', nameEn: 'SSE 50 ETF' },
      { symbol: '159919.SZ', nameZh: '沪深300ETF', nameEn: 'CSI 300 ETF' },
      { symbol: '588000.SH', nameZh: '科创50ETF', nameEn: 'STAR 50 ETF' },
      { symbol: '588080.SH', nameZh: '科创板50ETF', nameEn: 'STAR 50 ETF' },
      { symbol: '512100.SH', nameZh: '中证1000ETF', nameEn: 'CSI 1000 ETF' },
      { symbol: '159845.SZ', nameZh: '中证1000ETF', nameEn: 'CSI 1000 ETF' },
    ],
  },
  {
    key: 'sector',
    labelKey: 'dashboard.widgets.etfHeatmap.cnSector',
    items: [
      { symbol: '512880.SH', nameZh: '证券ETF', nameEn: 'Securities ETF' },
      { symbol: '512800.SH', nameZh: '银行ETF', nameEn: 'Banks ETF' },
      { symbol: '512690.SH', nameZh: '酒ETF', nameEn: 'Liquor ETF' },
      { symbol: '512170.SH', nameZh: '医疗ETF', nameEn: 'Healthcare ETF' },
      { symbol: '512480.SH', nameZh: '半导体ETF', nameEn: 'Semiconductor ETF' },
      { symbol: '515030.SH', nameZh: '新能源车ETF', nameEn: 'EV ETF' },
      { symbol: '515790.SH', nameZh: '光伏ETF', nameEn: 'Solar ETF' },
      { symbol: '512660.SH', nameZh: '军工ETF', nameEn: 'Defence ETF' },
    ],
  },
  {
    key: 'theme',
    labelKey: 'dashboard.widgets.etfHeatmap.cnTheme',
    items: [
      { symbol: '159915.SZ', nameZh: '创业板ETF', nameEn: 'ChiNext ETF' },
      { symbol: '159949.SZ', nameZh: '创业板50ETF', nameEn: 'ChiNext 50 ETF' },
      { symbol: '513050.SH', nameZh: '中概互联网ETF', nameEn: 'China Internet ETF' },
      { symbol: '513100.SH', nameZh: '纳指ETF', nameEn: 'Nasdaq 100 ETF' },
      { symbol: '513500.SH', nameZh: '标普500ETF', nameEn: 'S&P 500 ETF' },
      { symbol: '159920.SZ', nameZh: '恒生ETF', nameEn: 'Hang Seng ETF' },
      { symbol: '511990.SH', nameZh: '华宝添益', nameEn: 'Money Market ETF' },
      { symbol: '511880.SH', nameZh: '银华日利', nameEn: 'Money Market ETF' },
    ],
  },
];

function strengthOf(change: number): number {
  return Math.min(0.86, 0.2 + Math.min(6, Math.abs(change)) / 8);
}

function pctText(change: number | null): string {
  if (change === null || !Number.isFinite(change)) return '—';
  return `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`;
}

export default function CnEtfHeatmap() {
  const { t, i18n } = useTranslation();
  const zh = i18n.language.toLowerCase().startsWith('zh');
  const symbols = useMemo(() => ROWS.flatMap((row) => row.items.map((item) => item.symbol)), []);
  const { quotes, isLoading } = useQuotes(symbols, { staleTime: 15_000, refetchInterval: 30_000 });

  const nameOf = (item: EtfItem) => (zh ? item.nameZh : item.nameEn);

  return (
    <div className="cn-etf" data-testid="cn-etf-heatmap">
      <div className="cn-etf-head">
        <span className="cn-etf-title">{t('dashboard.widgets.etfHeatmap.cnTitle')}</span>
        <span className="cn-etf-legend" aria-hidden="true">
          <i className="cn-etf-swatch cn-etf-swatch--up" />
          {t('dashboard.widgets.etfHeatmap.cnUp')}
          <i className="cn-etf-swatch cn-etf-swatch--down" />
          {t('dashboard.widgets.etfHeatmap.cnDown')}
        </span>
        {isLoading && <Loader className="cn-etf-loader" />}
      </div>
      <div className="cn-etf-board">
        {ROWS.map((row) => (
          <div className="cn-etf-row" key={row.key}>
            <span className="cn-etf-row-label">{t(row.labelKey)}</span>
            <div className="cn-etf-cells">
              {row.items.map((item) => {
                const q = quotes[quoteKey(item.symbol)];
                const change = typeof q?.change_percent === 'number' ? q.change_percent : null;
                const weight = Math.max(1, Math.sqrt(Math.max(0, Number(q?.volume) || 0)));
                const cls = change === null || change === 0
                  ? 'is-flat'
                  : change > 0 ? 'is-up' : 'is-down';
                return (
                  <div
                    key={item.symbol}
                    className={`cn-etf-cell ${cls}`}
                    style={{ flexGrow: weight, ['--cn-strength' as string]: strengthOf(change ?? 0) }}
                    title={`${nameOf(item)} ${pctText(change)}`}
                  >
                    <span className="cn-etf-name">{nameOf(item)}</span>
                    <span className="cn-etf-pct">{pctText(change)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
