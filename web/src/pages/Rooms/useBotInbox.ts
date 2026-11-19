/** The bot inbox's snapshot read plus one live SSE tail for the page. */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getBotMessages, streamBotMessages, type BotMessageInfo } from '@/api/bots';
import { getGuestSent, type GuestMessage } from '@/api/guestDm';

const EMPTY: BotMessageInfo[] = [];

export function useBotInbox(workspaceId: string | null) {
  const query = useQuery({
    queryKey: ['bot-messages', workspaceId],
    queryFn: () => getBotMessages(workspaceId, 100),
    enabled: !!workspaceId,
  });
  const [messages, setMessages] = useState<BotMessageInfo[]>(EMPTY);
  // Sent guest messages are not in the inbox read (the recipient owns that
  // row), so the sidebar needs this second source to show a conversation the
  // user started before the other side answered.
  const sent = useQuery({
    queryKey: ['guest-sent'],
    queryFn: () => getGuestSent(200),
    enabled: !!workspaceId,
  });

  useEffect(() => {
    if (!workspaceId) {
      setMessages(EMPTY);
      return;
    }
    const snapshot = query.data?.messages ?? EMPTY;
    setMessages(snapshot);
    // The list read is the snapshot; the tail is what keeps an open page live.
    // Starting at the newest row means the overlap is deduped by message id.
    const stop = streamBotMessages(workspaceId, snapshot[0]?.created_at ?? null, {
      onMessage: (message) => {
        setMessages((current) =>
          current.some((row) => row.message_id === message.message_id)
            ? current
            : [message, ...current],
        );
      },
    });
    return stop;
  }, [workspaceId, query.data]);

  return { ...query, messages, sent: (sent.data?.messages ?? []) as GuestMessage[] };
}
