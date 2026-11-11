import { Suspense } from 'react';
import { Navigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import PageLoading from '@/components/PageLoading/PageLoading';
import { pagePluginForRoute } from './registry';
import { usePagePlugins } from './usePagePlugins';

/** The shell for every `/p/:pluginId` route: a page ships only if enabled. */
export function PluginPageHost() {
  const { pluginId = '' } = useParams();
  const plugin = pagePluginForRoute(pluginId);
  const { enabled, toggle, isLoading, isToggling } = usePagePlugins();
  const { t } = useTranslation();

  if (!plugin) return <Navigate to="/dashboard" replace />;
  if (isLoading) return <div data-page-plugin-host={plugin.id} data-page-plugin-state="loading"><PageLoading /></div>;

  if (!enabled.has(plugin.id)) {
    const Icon = plugin.icon;
    return (
      <main data-page-plugin-host={plugin.id} data-page-plugin-state="disabled" className="flex h-full items-center justify-center p-6">
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
            onClick={() => { void toggle({ pluginId: plugin.id, enabled: true }); }}
          >
            {t('plugins.builtin.enable')}
          </Button>
        </div>
      </main>
    );
  }

  const page = plugin.pages[0];
  if (!page) return <Navigate to="/dashboard" replace />;
  const Page = page.component;
  return (
    <div data-page-plugin-host={plugin.id} data-page-plugin-state="enabled">
      <Suspense fallback={<PageLoading />}>
        <Page />
      </Suspense>
    </div>
  );
}
