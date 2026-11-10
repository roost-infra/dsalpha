/**
 * A workspace's conversations, rendered inside its row in the navigation tree
 * as one recency-ordered stream: a bot's direct chat, a group chat and a
 * bot-to-bot exchange are peers, the way DS-Bot's home draws them. There is
 * no separate history list — a conversation is either a room or a bot.
 */
import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { BotInfo } from '@/api/bots';
import type { RoomInfo } from '@/api/rooms';
import { useBots } from '@/hooks/useBots';
import { useRooms } from '@/hooks/useRooms';
import { BotMark } from '@/components/bots/BotMark';
import { RoomAvatar } from '@/pages/Rooms/components/RoomAvatar';
import { buildBotPairs } from '@/pages/Rooms/botInbox';
import { useBotInbox } from '@/pages/Rooms/useBotInbox';
import { createThreadWithTitle } from '@/pages/ChatAgent/utils/api/threads';
import {
  buildConversationItems,
  formatActivity,
  type ConversationItem,
  type ConversationThread,
} from './conversations';
import './ConversationSections.css';

const EMPTY_ROOMS: RoomInfo[] = [];
const EMPTY_BOTS: BotInfo[] = [];
const EMPTY_THREADS: ConversationThread[] = [];

function plainPreview(text: string | null | undefined): string {
  return (text ?? '')
    .replace(/[#>*_`\[\]()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120);
}

export function WorkspaceConversations({
  workspaceId,
  threads = EMPTY_THREADS,
  onNavigate,
}: {
  workspaceId: string;
  /** The workspace's loaded threads, for a bot's private chat title and stamp. */
  threads?: ConversationThread[];
  onNavigate?: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const roomsQuery = useRooms(workspaceId, true);
  const botsQuery = useBots(workspaceId, true);
  const inbox = useBotInbox(workspaceId);
  const rooms = roomsQuery.data?.rooms ?? EMPTY_ROOMS;
  const bots = botsQuery.data?.bots ?? EMPTY_BOTS;
  const botsById = useMemo(() => new Map(bots.map((bot) => [bot.bot_id, bot])), [bots]);
  const pairs = useMemo(() => buildBotPairs(inbox.messages, botsById), [inbox.messages, botsById]);
  const items = useMemo(
    () => buildConversationItems(rooms, bots, pairs, threads),
    [rooms, bots, pairs, threads],
  );

  const notifyNavigate = () => {
    onNavigate?.();
    window.dispatchEvent(new Event('sidebar:navigate'));
  };

  const openBot = async (botId: string) => {
    const bot = botsById.get(botId);
    if (!bot) return;
    if (bot.primary_thread_id) {
      navigate(`/chat/t/${bot.primary_thread_id}`, { state: { workspaceId } });
      notifyNavigate();
      return;
    }
    const created = await createThreadWithTitle({
      workspaceId,
      firstQuery: '',
      title: bot.name,
      botId: bot.bot_id,
    });
    navigate(`/chat/t/${created.thread_id}`, { state: { workspaceId: created.workspace_id } });
    notifyNavigate();
  };

  const openRoom = (roomId: string) => {
    navigate(`/rooms?room=${encodeURIComponent(roomId)}`);
    notifyNavigate();
  };
  const openExchange = (key: string) => {
    navigate(`/rooms?exchange=${encodeURIComponent(key)}`);
    notifyNavigate();
  };

  const open = (item: ConversationItem) => {
    if (item.kind === 'room') openRoom(item.room.room_id);
    else if (item.kind === 'pair') openExchange(item.pair.key);
    else void openBot(item.bot.bot_id);
  };

  const label = (item: ConversationItem) => {
    if (item.kind === 'room') return item.room.name;
    if (item.kind === 'pair') return `${item.pair.left.name} ⇄ ${item.pair.right.name}`;
    return item.bot.name;
  };

  const preview = (item: ConversationItem) => {
    if (item.kind === 'room') {
      return plainPreview(item.room.preview) || t('rooms.previewEmpty');
    }
    if (item.kind === 'pair') {
      return plainPreview(item.pair.messages.at(-1)?.content) || t('rooms.previewEmpty');
    }
    if (item.thread?.title?.trim()) return item.thread.title.trim();
    return item.bot.status === 'paused'
      ? t('bots.pausedBadge')
      : t('rooms.privateOpen');
  };

  const avatar = (item: ConversationItem) => {
    if (item.kind === 'room') {
      return <RoomAvatar members={item.room.members ?? []} size={24} />;
    }
    if (item.kind === 'pair') {
      return (
        <span className="workspace-conversations__faces" aria-hidden>
          <BotMark bot={item.pair.left} size={16} decorative />
          <BotMark bot={item.pair.right} size={16} decorative />
        </span>
      );
    }
    return <BotMark bot={item.bot} size={19} decorative />;
  };

  const loading = roomsQuery.isLoading || botsQuery.isLoading;

  return (
    <div className="workspace-conversations" aria-label={t('conversations.title')}>
      {loading ? (
        <div className="workspace-conversations__quiet" role="status">
          {t('common.loading')}
        </div>
      ) : items.length === 0 ? (
        <div className="workspace-conversations__quiet">{t('nav.noConversations')}</div>
      ) : (
        items.map((item) => (
          <button
            key={item.key}
            type="button"
            data-nav-key={item.key}
            className="workspace-conversations__row"
            onClick={() => open(item)}
          >
            {avatar(item)}
            <span className="workspace-conversations__body">
              <span className="workspace-conversations__name">{label(item)}</span>
              <span className="workspace-conversations__preview">{preview(item)}</span>
            </span>
            <span className="workspace-conversations__when">
              {formatActivity(item.activity)}
            </span>
          </button>
        ))
      )}
    </div>
  );
}
