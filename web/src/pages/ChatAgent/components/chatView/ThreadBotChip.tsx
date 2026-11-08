/**
 * The bot a chat thread answers as, drawn in the chat header.
 *
 * The thread row carries only `bot_id` (the server resolves identity, not the
 * display), so this reads the row from the same detail query the composer
 * already keeps warm and then reads that bot. A thread with no bot — one the
 * resolver has never stamped, or the not-yet-created `__default__` thread —
 * draws nothing at all and the header keeps its generic shape.
 */
import { useQuery } from '@tanstack/react-query';
import { useBot } from '@/hooks/useBots';
import { threadDetailQuery } from '../../utils/threadQueries';

/** The avatar dict is open on the server (a JSONB column); a URL or an emoji
 *  is what this UI knows how to draw, and anything else falls back to the
 *  bot's initial. */
function BotAvatar({ avatar, name }: { avatar: Record<string, unknown>; name: string }) {
  const url = typeof avatar.url === 'string' && avatar.url.trim() ? avatar.url : null;
  const emoji = typeof avatar.emoji === 'string' && avatar.emoji.trim() ? avatar.emoji : null;
  if (url) {
    return <img src={url} alt="" className="h-4 w-4 shrink-0 rounded-full object-cover" />;
  }
  if (emoji) {
    return <span aria-hidden className="shrink-0 text-xs leading-none">{emoji}</span>;
  }
  const initial = name.trim().charAt(0).toUpperCase() || '·';
  return (
    <span
      aria-hidden
      className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[9px] font-semibold"
      style={{ backgroundColor: 'var(--color-bg-elevated)', color: 'var(--color-text-secondary)' }}
    >
      {initial}
    </span>
  );
}

export function ThreadBotChip({ threadId }: { threadId: string | null | undefined }) {
  const liveThreadId = threadId && threadId !== '__default__' ? threadId : null;
  const { data: thread } = useQuery({
    ...threadDetailQuery(liveThreadId ?? ''),
    enabled: !!liveThreadId,
  });
  const botId = thread?.bot_id ?? null;
  const { data: bot } = useBot(botId);

  if (!bot) return null;
  return (
    <span
      data-testid="thread-bot"
      title={bot.name}
      className="inline-flex min-w-0 max-w-44 shrink items-center gap-1.5 rounded-full border px-1.5 py-0.5"
      style={{ borderColor: 'var(--color-border-muted)' }}
    >
      <BotAvatar avatar={bot.avatar} name={bot.name} />
      <span className="truncate text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        {bot.name}
      </span>
    </span>
  );
}
