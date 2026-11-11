import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { buttonClass } from '@/components/ui/button-class';
import { usePagePlugins } from '@/plugins/usePagePlugins';
import { PAGE_PLUGINS } from '@/plugins/registry';
import './BuiltinPagePlugins.css';

/** Page plugins are shipped with the app; the only verb is enable/disable. */
export function BuiltinPagePlugins() {
  const { t } = useTranslation();
  const { enabled, toggle, isLoading, isError, isToggling } = usePagePlugins();

  if (isLoading) {
    return <p className="builtin-page-plugins__intro">{t('plugins.builtin.loading')}</p>;
  }
  if (isError) {
    return <p className="builtin-page-plugins__intro">{t('plugins.builtin.loadError')}</p>;
  }

  return (
    <div className="builtin-page-plugins">
      <p className="builtin-page-plugins__intro">
        {t('plugins.builtin.intro')}
      </p>
      <div className="builtin-page-plugins__grid">
        {PAGE_PLUGINS.map((plugin) => {
          const Icon = plugin.icon;
          const active = enabled.has(plugin.id);
          return (
            <article key={plugin.id} className="builtin-page-plugin-card">
              <span className="builtin-page-plugin-card__icon"><Icon /></span>
              <div className="builtin-page-plugin-card__body">
                <div className="builtin-page-plugin-card__title">
                  <h3>{t(plugin.nameKey)}</h3>
                  <Badge variant="muted">{t('plugins.builtin.builtIn')}</Badge>
                </div>
                <p>{t(plugin.descriptionKey)}</p>
                <span className="builtin-page-plugin-card__state">
                  {active ? t('plugins.builtin.enabled') : t('plugins.builtin.disabled')}
                </span>
              </div>
              <span className="builtin-page-plugin-card__actions">
                {active && plugin.pages[0] && (
                  <Link
                    to={plugin.pages[0].path}
                    className={buttonClass({ variant: 'ghost', size: 'sm' })}
                  >
                    {t('plugins.builtin.open')}
                  </Link>
                )}
                <Button
                  type="button"
                  variant={active ? 'outline' : 'default'}
                  size="sm"
                  disabled={isToggling}
                  onClick={() => { void toggle({ pluginId: plugin.id, enabled: !active }).catch(() => {}); }}
                >
                  {active ? t('plugins.builtin.disable') : t('plugins.builtin.enable')}
                </Button>
              </span>
            </article>
          );
        })}
      </div>
    </div>
  );
}
