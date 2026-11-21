import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/ui/error-banner';
import { ListSkeleton } from '@/components/mcp/McpPrimitives';
import { EmptyState } from '@/pages/Plugins/components/EmptyState';
import { failureText } from '@/lib/failureText';
import { useDebouncedValue } from '@/lib/useDebouncedValue';
import { useMarketBots, useMyMarketInstalls } from './hooks';
import { BotCard } from './components/BotCard';
import { BotDetailDialog, type InstallTarget } from './components/BotDetailDialog';
import { InstallDialog } from './components/InstallDialog';
import { categoryLabelOf } from './utils';
import './Store.css';

type StoreView = 'all' | 'installed';

/**
 * /store — the built-in Bot market, v1.
 *
 * Browse the platform's templates and install one into a workspace of your
 * own; there is no publishing, pricing or admin here. The list is the "All"
 * tab, the installs read is the "Installed" tab. Search and the category chips
 * narrow only the list they sit over. A card opens its template's detail in a
 * dialog; Install closes that and opens the workspace + name form, whose
 * success lands a new bot and refreshes the Installed tab.
 */
function Store() {
  const { t, i18n } = useTranslation();
  const [view, setView] = useState<StoreView>('all');
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<string | null>(null);
  const [detailSlug, setDetailSlug] = useState<string | null>(null);
  const [installTarget, setInstallTarget] = useState<InstallTarget | null>(null);

  // Every keystroke rekeys nothing: the request follows the rested text only.
  const restedQuery = useDebouncedValue(query.trim(), 250);
  const bots = useMarketBots(restedQuery, category);
  const installs = useMyMarketInstalls(view === 'installed');

  // The server labels the chips for the request's Accept-Language; the app's
  // own language setting is what the reader chose, so known ids win here and
  // the server's label is only the fallback (a new category the build's locale
  // files do not know yet).
  const categories = useMemo(() => {
    const known: Record<string, string> = {
      research: t('store.categories.research'),
      earnings: t('store.categories.earnings'),
      market: t('store.categories.market'),
      event: t('store.categories.event'),
      risk: t('store.categories.risk'),
    };
    return (bots.data?.categories ?? []).map((entry) => ({
      ...entry,
      label: known[entry.id] ?? entry.label,
    }));
  }, [bots.data?.categories, t]);
  const cards = bots.data?.bots ?? [];
  const filtered = restedQuery.length > 0 || category !== null;

  const botsFailure = failureText(bots.error, t('store.loadFailed'));
  const installsFailure = failureText(installs.error, t('store.installsLoadFailed'));

  const openInstall = (target: InstallTarget) => {
    setDetailSlug(null);
    setInstallTarget(target);
  };

  const onInstalled = () => {
    setInstallTarget(null);
    setView('installed');
  };

  const clearFilters = () => {
    setQuery('');
    setCategory(null);
  };

  const formatInstalledAt = (iso: string) => {
    const date = new Date(iso);
    return Number.isNaN(date.getTime())
      ? iso
      : date.toLocaleDateString(i18n.language);
  };

  return (
    <div className="store-page">
      <div className="chrome-drag-strip" aria-hidden="true" />
      <div className="store-scroll">
        <div className="store-container">
          <header className="store-header">
            <h1 className="store-title">{t('store.title')}</h1>
            <p className="store-tagline">{t('store.tagline')}</p>
            <p className="store-builtin-note">{t('store.builtinNote')}</p>
          </header>

          <div className="store-tabs" role="tablist" aria-label={t('store.title')}>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'all'}
              className={`store-tab${view === 'all' ? ' is-active' : ''}`}
              onClick={() => setView('all')}
            >
              {t('store.tabs.all')}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'installed'}
              className={`store-tab${view === 'installed' ? ' is-active' : ''}`}
              onClick={() => setView('installed')}
            >
              {t('store.tabs.installed')}
            </button>
          </div>

          {view === 'all' && (
            <div className="store-toolbar">
              <label className="store-search">
                <Search aria-hidden="true" className="h-4 w-4" />
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t('store.searchPlaceholder')}
                  aria-label={t('store.searchLabel')}
                />
              </label>

              <div className="store-categories" role="group" aria-label={t('store.categoryAll')}>
                <button
                  type="button"
                  className={`store-chip-button${category === null ? ' is-active' : ''}`}
                  aria-pressed={category === null}
                  onClick={() => setCategory(null)}
                >
                  {t('store.categoryAll')}
                </button>
                {categories.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    className={`store-chip-button${category === entry.id ? ' is-active' : ''}`}
                    aria-pressed={category === entry.id}
                    onClick={() => setCategory(entry.id)}
                  >
                    {entry.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {view === 'all' && (
            <section className="store-body" aria-label={t('store.tabs.all')}>
              {bots.isLoading && (
                <div className="store-grid" aria-hidden="true">
                  {Array.from({ length: 6 }, (_, index) => (
                    <div key={index} className="store-card store-card-skeleton animate-pulse" />
                  ))}
                </div>
              )}

              {!bots.isLoading && bots.isError && (
                <div className="store-state">
                  <ErrorBanner error={botsFailure} />
                  <Button variant="ghost" size="sm" onClick={() => void bots.refetch()}>
                    {t('common.retry')}
                  </Button>
                </div>
              )}

              {!bots.isLoading && !bots.isError && cards.length === 0 && (
                <EmptyState
                  message={filtered ? t('store.empty.filtered') : t('store.empty.all')}
                  action={
                    filtered ? (
                      <Button variant="outline" size="sm" onClick={clearFilters}>
                        {t('store.clearFilters')}
                      </Button>
                    ) : undefined
                  }
                />
              )}

              {!bots.isLoading && !bots.isError && cards.length > 0 && (
                <div className="store-grid">
                  {cards.map((bot) => (
                    <BotCard
                      key={bot.slug}
                      bot={bot}
                      categoryLabel={categoryLabelOf(categories, bot.category)}
                      onOpen={() => setDetailSlug(bot.slug)}
                    />
                  ))}
                </div>
              )}
            </section>
          )}

          {view === 'installed' && (
            <section className="store-body" aria-label={t('store.tabs.installed')}>
              {installs.isLoading && <ListSkeleton rows={4} />}

              {!installs.isLoading && installs.isError && (
                <div className="store-state">
                  <ErrorBanner error={installsFailure} />
                  <Button variant="ghost" size="sm" onClick={() => void installs.refetch()}>
                    {t('common.retry')}
                  </Button>
                </div>
              )}

              {!installs.isLoading &&
                !installs.isError &&
                (installs.data?.installs.length ?? 0) === 0 && (
                  <EmptyState
                    message={t('store.empty.installed')}
                    action={
                      <Button variant="outline" size="sm" onClick={() => setView('all')}>
                        {t('store.browseAll')}
                      </Button>
                    }
                  />
                )}

              {!installs.isLoading &&
                !installs.isError &&
                (installs.data?.installs.length ?? 0) > 0 && (
                  <ul className="store-install-list">
                    {installs.data!.installs.map((install) => (
                      <li key={install.install_id}>
                        <button
                          type="button"
                          className="store-install-row"
                          onClick={() => setDetailSlug(install.slug)}
                        >
                          <span className="store-install-name">{install.name}</span>
                          <span className="store-install-meta">
                            {t('store.version', { version: install.version })} ·{' '}
                            {install.workspace_name} · {formatInstalledAt(install.created_at)}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
            </section>
          )}
        </div>
      </div>

      {detailSlug && (
        <BotDetailDialog
          slug={detailSlug}
          categories={categories}
          onClose={() => setDetailSlug(null)}
          onInstall={openInstall}
        />
      )}

      {installTarget && (
        <InstallDialog
          target={installTarget}
          onClose={() => setInstallTarget(null)}
          onInstalled={onInstalled}
        />
      )}
    </div>
  );
}

export default Store;
