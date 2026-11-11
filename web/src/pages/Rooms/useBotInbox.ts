/** The bot inbox's snapshot read plus one live SSE tail for the page. */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getBotMessages, streamBotMessages, type BotMessageInfo } from '@/api/bots';

const EMPTY: BotMessageInfo[] = [];

export function useBotInbox(workspaceId: string | null) {
  const query = useQuery({
    queryKey: ['bot-messages', workspaceId],
    queryFn: () => getBotMessages(workspaceId, 100),
    enabled: !!workspaceId,
  });
  const [messages, setMessages] = useState<BotMessageInfo[]>(EMPTY);

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

  return { ...query, messages };
}
