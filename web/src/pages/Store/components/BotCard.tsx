import { useTranslation } from 'react-i18next';
import { Bot, Check, Sparkles } from 'lucide-react';
import type { MarketBotCard } from '../api';

/**
 * One template in the grid. The whole card is the button that opens its detail
 * view, so it carries no second control of its own; the marks a reader scans
 * for (featured, already installed) sit inside the same target.
 *
 * `categoryLabel` comes from the list answer's categories because the cards
 * carry a category id, not its display name.
 */
export function BotCard({
  bot,
  categoryLabel,
  onOpen,
}: {
  bot: MarketBotCard;
  categoryLabel?: string;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className="store-card"
      onClick={onOpen}
      aria-haspopup="dialog"
      aria-label={t('store.openBot', { name: bot.name })}
      data-testid={`store-card-${bot.slug}`}
    >
      <span className="store-card-top">
        <span className="store-card-mark" aria-hidden="true">
          <Bot className="h-4 w-4" />
        </span>
        <span className="store-card-titles">
          <span className="store-card-name">{bot.name}</span>
          {bot.featured && (
            <span className="store-card-featured">
              <Sparkles aria-hidden="true" className="h-3 w-3" />
              {t('store.featured')}
            </span>
          )}
        </span>
      </span>

      <span className="store-card-summary">{bot.summary}</span>

      {bot.tags.length > 0 && (
        <span className="store-card-tags">
          {bot.tags.map((tag) => (
            <span key={tag} className="store-tag">
              {tag}
            </span>
          ))}
        </span>
      )}

      <span className="store-card-foot">
        <span className="store-card-meta">
          {categoryLabel && <span>{categoryLabel}</span>}
          <span className="store-card-version">
            {t('store.version', { version: bot.version })}
          </span>
        </span>
        {bot.installed && (
          <span className="store-card-installed">
            <Check aria-hidden="true" className="h-3 w-3" />
            {t('store.installed')}
          </span>
        )}
      </span>
    </button>
  );
}
