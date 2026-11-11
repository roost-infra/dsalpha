import { Suspense } from 'react';
import { Navigate, useLocation, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import PageLoading from '@/components/PageLoading/PageLoading';
import { pluginPageForRoute } from './registry';
import { usePagePlugins } from './usePagePlugins';

/** The shell for every `/p/:pluginId` route: a page ships only if enabled. */
export function PluginPageHost() {
  const { pluginId = '' } = useParams();
  const location = useLocation();
  const resolved = pluginPageForRoute(pluginId);
  const { enabled, toggle, isLoading, isError, isToggling, refetch } = usePagePlugins();
  const { t } = useTranslation();

  if (!resolved) return <Navigate to="/dashboard" replace />;
  const { plugin, page } = resolved;

  // A plugin-id URL (`/p/market-center`) or an extra path segment normalizes
  // to the page's canonical path, keeping the query so deep links survive.
  if (location.pathname !== page.path) {
    return (
      <Navigate
        to={{ pathname: page.path, search: location.search, hash: location.hash }}
        replace
      />
    );
  }

  if (isLoading) {
    return (
      <div className="h-full" data-page-plugin-host={plugin.id} data-page-plugin-state="loading">
        <PageLoading />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex h-full w-full items-center justify-center p-6">
        <div className="w-full max-w-md rounded-xl border p-6" style={{ borderColor: 'var(--color-border-muted)', background: 'var(--color-bg-card)' }}>
          <h1 className="text-lg font-semibold">{t('plugins.builtin.loadError')}</h1>
          <Button type="button" className="mt-4" onClick={() => { void refetch(); }}>
            {t('common.retry')}
          </Button>
        </div>
      </div>
    );
  }

  if (!enabled.has(plugin.id)) {
    const Icon = plugin.icon;
    return (
      <div
        data-page-plugin-host={plugin.id}
        data-page-plugin-state="disabled"
        className="flex h-full w-full items-center justify-center p-6"
      >
        <div className="w-full max-w-md rounded-xl border p-6" style={{ borderColor: 'var(--color-border-muted)', background: 'var(--color-bg-card)' }}>
          <Icon className="h-8 w-8" style={{ color: 'var(--color-text-secondary)' }} aria-hidden />
          <h1 className="mt-4 text-lg font-semibold">{t(plugin.nameKey)}</h1>
          <p className="mt-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            {t(plugin.descriptionKey)}
          </p>
          <p className="mt-4 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {t('plugins.builtin.pageNotEnabled')}
          </p>
          <Button
            type="button"
            className="mt-4"
            disabled={isToggling}
            onClick={() => { void toggle({ pluginId: plugin.id, enabled: true }).catch(() => {}); }}
          >
            {t('plugins.builtin.enable')}
          </Button>
        </div>
      </div>
    );
  }

  const Page = page.component;
  return (
    <div
      className="h-full min-h-0"
      data-page-plugin-host={plugin.id}
      data-page-plugin-state="enabled"
    >
      <Suspense fallback={<PageLoading />}>
        <Page />
      </Suspense>
    </div>
  );
}
