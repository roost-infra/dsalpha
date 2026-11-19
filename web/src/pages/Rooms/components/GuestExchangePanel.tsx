/** A guest conversation: both sides' messages plus a composer once accepted. */
import { Fragment, useState, type FormEvent } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { BotMark } from '@/components/bots/BotMark';
import Markdown from '@/pages/ChatAgent/components/Markdown';
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
  return date.toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'short' });
}

export function GuestExchangePanel({
  pair,
  localBot,
  peerBot,
  loading,
  failed,
  canSend,
  onSend,
  onClose,
}: {
  pair: BotPair;
  localBot: PairBot;
  peerBot: PairBot;
  loading: boolean;
  failed: boolean;
  canSend: boolean;
  onSend: (text: string) => Promise<void>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  let lastDay = '';

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setError(null);
    try {
      await onSend(text);
      setDraft('');
    } catch {
      setError(t('rooms.guestSendFailed'));
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="rooms-bot-messages rooms-guest-messages" aria-label={t('rooms.guestMessagesTitle')}>
      <header className="rooms-bot-messages__header">
        <span className="rooms-bot-messages__pair">
          <BotMark bot={localBot} size={22} decorative />
          <span>{localBot.name}</span>
          <span className="rooms-bot-messages__swap" aria-hidden>⇄</span>
          <BotMark bot={peerBot} size={22} decorative />
          <span>{peerBot.name}</span>
          <span className="rooms-guest-messages__badge">{t('rooms.guestExternalBadge')}</span>
        </span>
        <Button variant="ghost" size="icon" aria-label={t('common.close')} onClick={onClose}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </header>
      {loading && pair.messages.length === 0 ? (
        <div className="rooms-bot-messages__state" role="status">{t('common.loading')}</div>
      ) : failed ? (
        <div className="rooms-bot-messages__state" role="status">{t('rooms.guestLoadFailed')}</div>
      ) : pair.messages.length === 0 ? (
        <div className="rooms-bot-messages__state">{t('rooms.guestEmpty')}</div>
      ) : (
        <div className="rooms-bot-messages__list">
          {[...pair.messages]
            .sort((a, b) => Date.parse(a.created_at ?? '') - Date.parse(b.created_at ?? ''))
            .map((message) => {
              const mine = message.from_id === localBot.bot_id;
              const sender = mine ? localBot : peerBot;
              const day = dayKey(message.created_at);
              const showDay = Boolean(day) && day !== lastDay;
              if (showDay) lastDay = day;
              return (
                <Fragment key={message.message_id}>
                  {showDay && <div className="rooms-bot-messages__day">{dayLabel(message.created_at)}</div>}
                  <article className={`rooms-bot-messages__row rooms-bot-messages__row--exchange rooms-guest-messages__row${mine ? ' rooms-guest-messages__row--mine' : ''}`}>
                    <span className="rooms-bot-messages__lead">
                      <BotMark bot={sender} size={22} decorative />
                    </span>
                    <div className="rooms-bot-messages__content">
                      <span className="rooms-bot-messages__name">
                        {mine ? t('rooms.guestYou') : sender.name}
                        {message.status !== 'delivered' && message.status !== 'consumed' && (
                          <span className="rooms-guest-messages__status"> · {message.status}</span>
                        )}
                      </span>
                      <div className="rooms-bot-messages__body">
                        <Markdown content={message.content} variant="chat" />
                      </div>
                    </div>
                  </article>
                </Fragment>
              );
            })}
        </div>
      )}
      {!canSend ? (
        <p className="rooms-guest-messages__waiting">{t('rooms.guestWaitingAccept')}</p>
      ) : (
        <form className="rooms-guest-messages__composer" onSubmit={submit}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={t('rooms.guestSendPlaceholder')}
            rows={2}
            disabled={sending}
            aria-label={t('rooms.guestSendPlaceholder')}
          />
          <Button type="submit" disabled={sending || !draft.trim()}>
            {sending ? t('common.sending') : t('rooms.guestSend')}
          </Button>
        </form>
      )}
      {error && <p className="rooms-guest-messages__error" role="alert">{error}</p>}
      <p className="rooms-ai-disclaimer">{t('chat.aiDisclaimer')}</p>
    </section>
  );
}
