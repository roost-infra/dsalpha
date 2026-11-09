/**
 * One pair's exchange, opened from the bot inbox: two bots' messages as a
 * conversation, with the same date separators and conclusion bubbles as the
 * group log. It is not a session transcript: no tool cards live here.
 */
import { Fragment } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { BotMark } from '@/components/bots/BotMark';
import Markdown from '@/pages/ChatAgent/components/Markdown';
import type { BotMessageInfo } from '@/api/bots';
import type { BotPair, PairBot } from '../botInbox';

function dayKey(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toDateString();
}

function dayLabel(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  });
}

export function BotExchangePanel({
  pair,
  messages,
  loading,
  failed,
  onClose,
}: {
  pair: BotPair;
  messages: BotMessageInfo[];
  loading: boolean;
  failed: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const senderOf = (message: BotMessageInfo): PairBot =>
    message.from_id === pair.right.bot_id ? pair.right : pair.left;
  let lastDay = '';

  return (
    <aside className="rooms-bot-messages" role="dialog" aria-modal="true" aria-label={t('rooms.botMessagesTitle')}>
      <header className="rooms-bot-messages__header">
        <span className="rooms-bot-messages__pair">
          <BotMark bot={pair.left} size={22} decorative />
          <span>{pair.left.name}</span>
          <span className="rooms-bot-messages__swap" aria-hidden>⇄</span>
          <BotMark bot={pair.right} size={22} decorative />
          <span>{pair.right.name}</span>
        </span>
        <Button variant="ghost" size="icon" aria-label={t('common.close')} onClick={onClose}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </header>
      {loading && messages.length === 0 ? (
        <div className="rooms-bot-messages__state" role="status">{t('common.loading')}</div>
      ) : failed ? (
        <div className="rooms-bot-messages__state" role="status">{t('rooms.botMessagesFailed')}</div>
      ) : messages.length === 0 ? (
        <div className="rooms-bot-messages__state">{t('rooms.botMessagesEmpty')}</div>
      ) : (
        <div className="rooms-bot-messages__list">
          {messages.map((message) => {
            const sender = senderOf(message);
            const day = dayKey(message.created_at);
            const showDay = Boolean(day) && day !== lastDay;
            if (showDay) lastDay = day;
            return (
              <Fragment key={message.message_id}>
                {showDay && <div className="rooms-bot-messages__day">{dayLabel(message.created_at)}</div>}
                <article className="rooms-bot-messages__row rooms-bot-messages__row--exchange">
                  <span className="rooms-bot-messages__lead">
                    <BotMark bot={sender} size={22} decorative />
                  </span>
                  <div className="rooms-bot-messages__content">
                    <span className="rooms-bot-messages__name">{sender.name}</span>
                    <div className="rooms-bot-messages__body">
                      <Markdown content={message.content} variant="chat" />
                    </div>
                    <span className="rooms-bot-messages__meta">
                      {message.kind} · {message.status}
                    </span>
                  </div>
                </article>
              </Fragment>
            );
          })}
        </div>
      )}
      {messages.length > 0 && <p className="rooms-ai-disclaimer">{t('chat.aiDisclaimer')}</p>}
    </aside>
  );
}
