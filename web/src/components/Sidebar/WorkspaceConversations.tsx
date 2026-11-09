/**
 * A workspace's conversations, rendered inside its row in the navigation tree:
 * the room list, the workspace's bot chats and the bot-to-bot exchanges all
 * belong under the workspace they live in, not in a global strip above it.
 */
import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useBots } from '@/hooks/useBots';
import { useRooms } from '@/hooks/useRooms';
import { BotMark } from '@/components/bots/BotMark';
import { RoomAvatar } from '@/pages/Rooms/components/RoomAvatar';
import { buildBotPairs } from '@/pages/Rooms/botInbox';
import { useBotInbox } from '@/pages/Rooms/useBotInbox';
import { createThreadWithTitle } from '@/pages/ChatAgent/utils/api/threads';
import './ConversationSections.css';

function plainPreview(text: string | null | undefined): string {
  return (text ?? '')
    .replace(/[#>*_`\[\]()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120);
}

export function WorkspaceConversations({
  workspaceId,
  onNavigate,
}: {
  workspaceId: string;
  onNavigate?: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const roomsQuery = useRooms(workspaceId, true);
  const botsQuery = useBots(workspaceId, true);
  const inbox = useBotInbox(workspaceId);
  const rooms = roomsQuery.data?.rooms ?? [];
  const bots = botsQuery.data?.bots ?? [];
  const botsById = useMemo(() => new Map(bots.map((bot) => [bot.bot_id, bot])), [bots]);
  const pairs = useMemo(() => buildBotPairs(inbox.messages, botsById), [inbox.messages, botsById]);

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

  const notifyNavigate = () => {
    onNavigate?.();
    window.dispatchEvent(new Event('sidebar:navigate'));
  };

  const openRoom = (roomId: string) => {
    navigate(`/rooms?room=${encodeURIComponent(roomId)}`);
    notifyNavigate();
  };
  const openExchange = (key: string) => {
    navigate(`/rooms?exchange=${encodeURIComponent(key)}`);
    notifyNavigate();
  };

  return (
    <div className="workspace-conversations" aria-label={t('conversations.title')}>
      <div className="workspace-conversations__section">{t('rooms.roomsSection')}</div>
      {roomsQuery.isLoading ? (
        <div className="workspace-conversations__quiet" role="status">{t('common.loading')}</div>
      ) : rooms.length === 0 ? (
        <div className="workspace-conversations__quiet">{t('conversations.noRooms')}</div>
      ) : (
        rooms.map((room) => (
          <button
            key={room.room_id}
            type="button"
            className="workspace-conversations__row"
            onClick={() => openRoom(room.room_id)}
          >
            <RoomAvatar members={room.members ?? []} size={24} />
            <span className="workspace-conversations__body">
              <span className="workspace-conversations__name">{room.name}</span>
              <span className="workspace-conversations__preview">
                {plainPreview(room.preview) || t('rooms.previewEmpty')}
              </span>
            </span>
          </button>
        ))
      )}

      <div className="workspace-conversations__section">{t('rooms.privateSection')}</div>
      {bots.length === 0 ? (
        <div className="workspace-conversations__quiet">{t('rooms.privateEmpty')}</div>
      ) : (
        bots.map((bot) => (
          <button
            key={bot.bot_id}
            type="button"
            className="workspace-conversations__row"
            onClick={() => { void openBot(bot.bot_id); }}
          >
            <BotMark bot={bot} size={19} decorative />
            <span className="workspace-conversations__body">
              <span className="workspace-conversations__name">{bot.name}</span>
              <span className="workspace-conversations__preview">
                {bot.status === 'paused' ? t('bots.pausedBadge') : t('rooms.privateOpen')}
              </span>
            </span>
          </button>
        ))
      )}

      <div className="workspace-conversations__section">{t('rooms.botMessagesSection')}</div>
      {pairs.length === 0 ? (
        <div className="workspace-conversations__quiet">{t('rooms.botMessagesEmpty')}</div>
      ) : (
        pairs.map((pair) => (
          <button
            key={pair.key}
            type="button"
            className="workspace-conversations__row"
            onClick={() => openExchange(pair.key)}
          >
            <span className="workspace-conversations__faces" aria-hidden>
              <BotMark bot={pair.left} size={16} decorative />
              <BotMark bot={pair.right} size={16} decorative />
            </span>
            <span className="workspace-conversations__body">
              <span className="workspace-conversations__name">
                {pair.left.name} ⇄ {pair.right.name}
              </span>
              <span className="workspace-conversations__preview">
                {plainPreview(pair.messages.at(-1)?.content) || t('rooms.previewEmpty')}
              </span>
            </span>
          </button>
        ))
      )}
    </div>
  );
}
