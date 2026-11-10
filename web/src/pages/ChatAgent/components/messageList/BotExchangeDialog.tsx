/** The full exchange behind a delivered bot message, opened from that row. */
import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { getBotMessages, type BotMessageInfo } from '@/api/bots';
import { useBots } from '@/hooks/useBots';
import { BotExchangePanel } from '@/pages/Rooms/components/BotExchangePanel';
import { buildBotPairs } from '@/pages/Rooms/botInbox';
import '@/pages/Rooms/Rooms.css';
import './BotExchangeDialog.css';

const EMPTY: BotMessageInfo[] = [];

export function BotExchangeDialog({
  workspaceId,
  messageId,
  onClose,
}: {
  workspaceId: string;
  messageId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const messagesQuery = useQuery({
    queryKey: ['bot-messages', workspaceId],
    queryFn: () => getBotMessages(workspaceId, 100),
    enabled: !!workspaceId,
    staleTime: 30_000,
  });
  const { data: botsData } = useBots(workspaceId, true);
  const messages = messagesQuery.data?.messages ?? EMPTY;
  const botsById = new Map((botsData?.bots ?? []).map((bot) => [bot.bot_id, bot]));
  const anchor = messages.find((message) => message.message_id === messageId);
  const pairKey = anchor ? [anchor.from_id, anchor.to_bot_id].sort().join('|') : null;
  const pair = pairKey
    ? buildBotPairs(messages, botsById).find((candidate) => candidate.key === pairKey) ?? null
    : null;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return createPortal(
    <div
      className="bot-exchange-dialog"
      role="dialog"
      aria-modal="true"
      aria-label={t('chat.botMessage.openExchange')}
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
    >
      <div className="bot-exchange-dialog__sheet">
        {pair ? (
          <BotExchangePanel
            pair={pair}
            messages={pair.messages}
            loading={messagesQuery.isLoading}
            failed={messagesQuery.isError}
            onClose={onClose}
          />
        ) : (
          <div className="bot-exchange-dialog__state" role="status">
            {messagesQuery.isLoading
              ? t('common.loading')
              : messagesQuery.isError
                ? t('rooms.botMessagesFailed')
                : t('chat.botMessage.exchangeUnavailable')}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
