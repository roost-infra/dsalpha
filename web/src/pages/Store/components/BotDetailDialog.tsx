import { useTranslation } from 'react-i18next';
import { Check, Sparkles } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/ui/error-banner';
import { ListSkeleton } from '@/components/mcp/McpPrimitives';
import { failureText } from '@/lib/failureText';
import { useMarketBot } from '../hooks';
import { categoryLabelOf } from '../utils';
import type { MarketCategory } from '../api';

/** What the install dialog needs from whichever card opened it. */
export interface InstallTarget {
  slug: string;
  name: string;
}

/**
 * One template's full page in a dialog: who it is, the persona it installs,
 * the tools and skills it copies, where it already lives, and the one write —
 * install it somewhere else. Mounted only while a card is open, so its detail
 * query starts with the click and stops when the dialog closes.
 */
export function BotDetailDialog({
  slug,
  categories,
  onClose,
  onInstall,
}: {
  slug: string;
  categories?: readonly MarketCategory[];
  onClose: () => void;
  onInstall: (target: InstallTarget) => void;
}) {
  const { t } = useTranslation();
  const { data, isLoading, isError, error, refetch } = useMarketBot(slug);
  const failure = failureText(error, t('store.detail.loadFailed'));
  const categoryLabel = categoryLabelOf(categories, data?.category);

  const title = data?.name ?? slug;
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        className="store-dialog store-detail-dialog"
        style={{ backgroundColor: 'var(--color-bg-page)', borderColor: 'var(--color-border-muted)' }}
      >
        <DialogHeader>
          <DialogTitle className="store-dialog-title">
            {data?.icon && <span className="store-detail-icon" aria-hidden="true">{data.icon}</span>}
            {title}
          </DialogTitle>
          <DialogDescription>
            {data?.summary ?? t('store.detail.loading')}
          </DialogDescription>
        </DialogHeader>

        {isLoading && <ListSkeleton rows={4} />}

        {!isLoading && isError && (
          <div className="flex flex-col items-start gap-2">
            <ErrorBanner error={failure} />
            <Button variant="ghost" size="sm" onClick={() => void refetch()}>
              {t('common.retry')}
            </Button>
          </div>
        )}

        {!isLoading && !isError && data && (
          <div className="store-detail-body">
            <div className="store-detail-meta">
              <span className="store-tag">
                {t('store.version', { version: data.version })}
              </span>
              {categoryLabel && <span className="store-tag">{categoryLabel}</span>}
              {data.featured && (
                <span className="store-card-featured">
                  <Sparkles aria-hidden="true" className="h-3 w-3" />
                  {t('store.featured')}
                </span>
              )}
            </div>

            {data.tags.length > 0 && (
              <div className="store-chip-row">
                {data.tags.map((tag) => (
                  <span key={tag} className="store-tag">
                    {tag}
                  </span>
                ))}
              </div>
            )}

            {data.description && (
              <p className="store-detail-description">{data.description}</p>
            )}

            <section className="store-detail-section">
              <h3 className="store-detail-label">{t('store.detail.persona')}</h3>
              <p className="store-detail-persona">
                {data.persona || t('store.detail.noPersona')}
              </p>
            </section>

            <section className="store-detail-section">
              <h3 className="store-detail-label">{t('store.detail.tools')}</h3>
              {data.tools.length > 0 ? (
                <div className="store-chip-row">
                  {data.tools.map((tool) => (
                    <span key={tool} className="store-chip">
                      {tool}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="store-detail-muted">{t('store.detail.noTools')}</p>
              )}
            </section>

            <section className="store-detail-section">
              <h3 className="store-detail-label">{t('store.detail.skills')}</h3>
              {data.skills.length > 0 ? (
                <div className="store-chip-row">
                  {data.skills.map((skill) => (
                    <span key={skill} className="store-chip">
                      {skill}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="store-detail-muted">{t('store.detail.noSkills')}</p>
              )}
            </section>

            <section className="store-detail-section">
              <h3 className="store-detail-label">{t('store.detail.installs')}</h3>
              {data.installs.length > 0 ? (
                <ul className="store-install-locations">
                  {data.installs.map((install) => (
                    <li key={`${install.workspace_id}:${install.bot_id}`}>
                      <Check aria-hidden="true" className="h-3.5 w-3.5" />
                      {t('store.detail.installedIn', { workspace: install.workspace_name })}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="store-detail-muted">{t('store.detail.noInstalls')}</p>
              )}
            </section>

            <p className="store-detail-note">{t('store.detail.deferredNote')}</p>
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>{t('common.close')}</Button>
          <Button
            disabled={!data}
            onClick={() => {
              if (!data) return;
              onInstall({ slug: data.slug, name: data.name });
            }}
          >
            {t('store.install')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
