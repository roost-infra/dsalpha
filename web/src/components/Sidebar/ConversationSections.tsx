/**
 * The app sidebar's conversation navigator: group chats, direct bot chats and
 * bot-to-bot exchanges for the workspace in view. It is the one entry point
 * for rooms now that /rooms is no longer a primary tab; the page itself stays
 * reachable by URL and deep links.
 */
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { MessageSquare } from 'lucide-react';
import { useAllWorkspaces } from '@/hooks/useAllWorkspaces';
import { useBots } from '@/hooks/useBots';
import { useRoom, useRooms } from '@/hooks/useRooms';
import { BotMark } from '@/components/bots/BotMark';
import { RoomAvatar } from '@/pages/Rooms/components/RoomAvatar';
import { buildBotPairs } from '@/pages/Rooms/botInbox';
import { useBotInbox } from '@/pages/Rooms/useBotInbox';
import { createThreadWithTitle } from '@/pages/ChatAgent/utils/api/threads';
import { useChatRoute } from './useChatRoute';
import './ConversationSections.css';

const WORKSPACE_KEY = 'conversation.workspace';

export function ConversationSections() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const { currentWorkspaceId } = useChatRoute();
  const onRooms = location.pathname === '/rooms' || location.pathname.startsWith('/rooms/');
  const roomId = onRooms ? params.get('room') : null;
  const roomQuery = useRoom(roomId);
  const { data: workspacesData } = useAllWorkspaces({ includeHome: true });
  const workspaces = workspacesData?.workspaces ?? [];

  const stored = (() => {
    try {
      return window.localStorage.getItem(WORKSPACE_KEY);
    } catch {
      return null;
    }
  })();
  const [choice, setChoice] = useState<string | null>(stored);
  const validChoice = workspaces.some((ws) => ws.workspace_id === choice) ? choice : null;
  const fallback = (workspaces.find((ws) => !ws.is_home) ?? workspaces[0])?.workspace_id ?? null;
  const workspaceId =
    currentWorkspaceId ?? roomQuery.data?.workspace_id ?? validChoice ?? fallback;
  const workspace = workspaces.find((ws) => ws.workspace_id === workspaceId);

  useEffect(() => {
    if (workspaceId) {
      try {
        window.localStorage.setItem(WORKSPACE_KEY, workspaceId);
      } catch {
        // Private mode only costs the remembered choice.
      }
    }
  }, [workspaceId]);

  const roomsQuery = useRooms(workspaceId, !!workspaceId);
  const botsQuery = useBots(workspaceId, !!workspaceId);
  const inbox = useBotInbox(workspaceId);
  const rooms = roomsQuery.data?.rooms ?? [];
  const bots = botsQuery.data?.bots ?? [];
  const botsById = useMemo(() => new Map(bots.map((bot) => [bot.bot_id, bot])), [bots]);
  const pairs = useMemo(() => buildBotPairs(inbox.messages, botsById), [inbox.messages, botsById]);

  const openBot = async (botId: string) => {
    const bot = botsById.get(botId);
    if (!bot || !workspaceId) return;
    if (bot.primary_thread_id) {
      navigate(`/chat/t/${bot.primary_thread_id}`, { state: { workspaceId } });
      return;
    }
    const created = await createThreadWithTitle({
      workspaceId,
      firstQuery: '',
      title: bot.name,
      botId: bot.bot_id,
    });
    navigate(`/chat/t/${created.thread_id}`, { state: { workspaceId: created.workspace_id } });
  };

  const openRoom = (id: string) => navigate(`/rooms?room=${encodeURIComponent(id)}`);
  const openExchange = (key: string) =>
    navigate(`/rooms?exchange=${encodeURIComponent(key)}`);

  if (!workspaceId) return null;

  return (
    <div className="conversation-nav" aria-label={t('conversations.title')}>
      <div className="conversation-nav__head">
        <span className="conversation-nav__title">{t('conversations.title')}</span>
       {workspaces.length > 1 && (
          <select
            className="conversation-nav__workspace"
            aria-label={t('conversations.workspace')}
            value={workspaceId}
            onChange={(event) => setChoice(event.target.value)}
          >
            {workspaces.map((ws) => (
              <option key={ws.workspace_id} value={ws.workspace_id}>
                {ws.name}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="conversation-nav__section">
        <span className="conversation-nav__label">{t('rooms.roomsSection')}</span>
      </div>
      {roomsQuery.isLoading ? (
        <div className="conversation-nav__quiet" role="status">{t('common.loading')}</div>
      ) : rooms.length === 0 ? (
        <div className="conversation-nav__quiet">{t('conversations.noRooms')}</div>
      ) : (
        rooms.map((room) => (
          <button
            key={room.room_id}
            type="button"
            className="conversation-nav__row"
            onClick={() => openRoom(room.room_id)}
          >
            <RoomAvatar members={room.members ?? []} size={26} />
            <span className="conversation-nav__body">
              <span className="conversation-nav__name">{room.name}</span>
              <span className="conversation-nav__preview">
                {room.preview?.replace(/\s+/g, ' ').trim() || t('rooms.previewEmpty')}
              </span>
            </span>
          </button>
        ))
      )}

      <div className="conversation-nav__section">
        <span className="conversation-nav__label">{t('rooms.privateSection')}</span>
      </div>
      {bots.length === 0 ? (
        <div className="conversation-nav__quiet">{t('rooms.privateEmpty')}</div>
      ) : (
        bots.map((bot) => (
          <button
            key={bot.bot_id}
            type="button"
            className="conversation-nav__row"
            onClick={() => { void openBot(bot.bot_id); }}
          >
            <BotMark bot={bot} size={20} decorative />
            <span className="conversation-nav__body">
              <span className="conversation-nav__name">{bot.name}</span>
              <span className="conversation-nav__preview">
                {bot.status === 'paused' ? t('bots.pausedBadge') : t('rooms.privateOpen')}
              </span>
            </span>
          </button>
        ))
      )}

      <div className="conversation-nav__section">
        <span className="conversation-nav__label">{t('rooms.botMessagesSection')}</span>
      </div>
      {pairs.length === 0 ? (
        <div className="conversation-nav__quiet">{t('rooms.botMessagesEmpty')}</div>
      ) : (
        pairs.map((pair) => (
          <button
            key={pair.key}
            type="button"
            className="conversation-nav__row"
            onClick={() => openExchange(pair.key)}
          >
            <span className="conversation-nav__faces" aria-hidden>
              <BotMark bot={pair.left} size={17} decorative />
              <BotMark bot={pair.right} size={17} decorative />
            </span>
            <span className="conversation-nav__body">
              <span className="conversation-nav__name">
                {pair.left.name} ⇄ {pair.right.name}
              </span>
              <span className="conversation-nav__preview">
                {pair.messages.at(-1)?.content.replace(/\s+/g, ' ').trim() || t('rooms.previewEmpty')}
              </span>
            </span>
          </button>
        ))
      )}
      {workspace && (
        <div className="conversation-nav__footer">
          <MessageSquare className="h-3 w-3" aria-hidden />
          <span>{workspace.name}</span>
        </div>
      )}
    </div>
  );
}
