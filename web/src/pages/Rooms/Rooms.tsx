/**
 * /rooms — group chats where a few bots share one log.
 *
 * The page is the list of rooms beside the one that is open. The room in the
 * URL (`?room=`) is the open one, so a link to a room is a link somebody can
 * send; the workspace picker narrows the list, and a room is always created in
 * the workspace it is showing. On a phone the list and the panel swap places
 * (see Rooms.css), which keeps the composer above the tab bar.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Bot as BotIcon, MessageSquare, MessagesSquare, Plus, UsersRound, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/ui/error-banner';
import { Select } from '@/components/ui/select';
import { useAllWorkspaces } from '@/hooks/useAllWorkspaces';
import { useBots } from '@/hooks/useBots';
import { useRoom, useRooms } from '@/hooks/useRooms';
import type { RoomInfo } from '@/api/rooms';
import { getBotMessages, type BotInfo, type BotMessageInfo } from '@/api/bots';
import { BotMark } from '@/components/bots/BotMark';
import Markdown from '@/pages/ChatAgent/components/Markdown';
import { createThreadWithTitle } from '@/pages/ChatAgent/utils/api/threads';
import { failureText } from '@/lib/failureText';
import { responderLabelKey } from './roomsCopy';
import CreateRoomDialog from './components/CreateRoomDialog';
import RoomPanel from './components/RoomPanel';
import './Rooms.css';

/** The bot-to-bot inbox, opened from the left rail: who sent what to which bot. */
function BotMessagesDrawer({
  messages,
  loading,
  failed,
  onClose,
}: {
  messages: BotMessageInfo[];
  loading: boolean;
  failed: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <aside className="rooms-bot-messages" role="dialog" aria-modal="true" aria-label={t('rooms.botMessagesTitle')}>
      <header className="rooms-bot-messages__header">
        <span>{t('rooms.botMessagesTitle')}</span>
        <Button variant="ghost" size="icon" aria-label={t('common.close')} onClick={onClose}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </header>
      {loading ? (
        <div className="rooms-bot-messages__state" role="status">{t('common.loading')}</div>
      ) : failed ? (
        <div className="rooms-bot-messages__state" role="status">{t('rooms.botMessagesFailed')}</div>
      ) : messages.length === 0 ? (
        <div className="rooms-bot-messages__state">{t('rooms.botMessagesEmpty')}</div>
      ) : (
        <div className="rooms-bot-messages__list">
          {messages.map((message) => (
            <article className="rooms-bot-messages__row" key={message.message_id}>
              <div className="rooms-bot-messages__route">
                <span>{message.from_name || t('rooms.you')}</span>
                <span aria-hidden>→</span>
                <span>{message.to_name}</span>
                <span className="rooms-bot-messages__meta">{message.kind} · {message.status}</span>
              </div>
              <div className="rooms-bot-messages__body">
                <Markdown content={message.content} variant="compact" />
              </div>
            </article>
          ))}
        </div>
      )}
    </aside>
  );
}

function RoomListRow({
  room,
  active,
  onOpen,
}: {
  room: RoomInfo;
  active: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className={active ? 'rooms-list__row is-active' : 'rooms-list__row'}
      aria-current={active ? 'true' : undefined}
      onClick={onOpen}
    >
      <span className="rooms-list__name">
        <MessagesSquare className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="rooms-list__name-text">{room.name}</span>
        {room.status === 'archived' && (
          <Badge variant="muted">{t('rooms.archivedBadge')}</Badge>
        )}
      </span>
      <span className="rooms-list__meta">{t(responderLabelKey(room.responder))}</span>
    </button>
  );
}

export default function Rooms() {
  const { t } = useTranslation();
  const {
    data: workspacesData,
    isLoading: workspacesLoading,
    isError: workspacesFailed,
    error: workspacesError,
    refetch: refetchWorkspaces,
  } = useAllWorkspaces({ includeHome: true });
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [workspaceChoice, setWorkspaceChoice] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [botMessagesOpen, setBotMessagesOpen] = useState(false);
  const [openingBotId, setOpeningBotId] = useState<string | null>(null);

  const workspaces = useMemo(() => workspacesData?.workspaces ?? [], [workspacesData]);
  const workspacesReady = !workspacesLoading;
  const fallbackWorkspaceId = useMemo(
    () => (workspaces.find((workspace) => !workspace.is_home) ?? workspaces[0])?.workspace_id ?? null,
    [workspaces],
  );
  const chosenWorkspaceId =
    workspaceChoice && workspaces.some((workspace) => workspace.workspace_id === workspaceChoice)
      ? workspaceChoice
      : null;

  const selectedRoomId = searchParams.get('room');
  // A deep link names its room's workspace through the room row, so the picker
  // follows it instead of leaving the list on another workspace. The page and
  // the panel read the same detail key, so this costs no second request.
  const linkedRoomQuery = useRoom(selectedRoomId);
  const linkedWorkspaceId = selectedRoomId ? (linkedRoomQuery.data?.workspace_id ?? null) : null;
  const workspaceId = chosenWorkspaceId ?? linkedWorkspaceId ?? fallbackWorkspaceId;
  const roomsQuery = useRooms(workspaceId, workspacesReady);
  const rooms = roomsQuery.data?.rooms ?? [];
  const maxBots = roomsQuery.data?.max_bots ?? 12;
  const botsQuery = useBots(workspaceId, !!workspaceId);
  // The bot-to-bot inbox is a read of the durable bot_messages rows, not of a
  // thread: it is how a reader sees A→B without opening B's private chat.
  const botMessages = useQuery({
    queryKey: ['bot-messages', workspaceId],
    queryFn: () => getBotMessages(workspaceId, 50),
    enabled: !!workspaceId,
  });
  const bots = botsQuery.data?.bots ?? [];
  const openPrivateChat = async (bot: BotInfo) => {
    if (!workspaceId || openingBotId) return;
    setOpeningBotId(bot.bot_id);
    try {
      const created = await createThreadWithTitle({
        workspaceId,
        firstQuery: '',
        title: bot.name,
        botId: bot.bot_id,
      });
      navigate(`/chat/t/${created.thread_id}`, {
        state: { workspaceId: created.workspace_id },
      });
    } finally {
      setOpeningBotId(null);
    }
  };
  // A link that names a room the server refuses is dropped from the URL rather
  // than left over an empty panel.
  useEffect(() => {
    if (!selectedRoomId || workspacesLoading || !linkedRoomQuery.isError) return;
    const next = new URLSearchParams(searchParams);
    next.delete('room');
    setSearchParams(next, { replace: true });
  }, [selectedRoomId, workspacesLoading, linkedRoomQuery.isError, searchParams, setSearchParams]);

  const openRoom = (roomId: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (roomId) next.set('room', roomId);
    else next.delete('room');
    setSearchParams(next, { replace: true });
  };

  const changeWorkspace = (nextWorkspaceId: string) => {
    setWorkspaceChoice(nextWorkspaceId);
    openRoom(null);
  };

  return (
    <div className={selectedRoomId ? 'rooms-page rooms-page--detail' : 'rooms-page'}>
      <header className="rooms-page__header">
        <div className="rooms-page__title">
          <UsersRound className="h-4.5 w-4.5 shrink-0" aria-hidden />
          <h1>{t('rooms.title')}</h1>
          <span className="rooms-page__subtitle">{t('rooms.description')}</span>
        </div>
        <div className="rooms-page__actions">
          {workspaces.length > 0 && (
            <Select
              className="rooms-page__workspace"
              aria-label={t('rooms.workspace')}
              value={workspaceId ?? ''}
              onChange={(event) => changeWorkspace(event.target.value)}
            >
              {workspaces.map((workspace) => (
                <option key={workspace.workspace_id} value={workspace.workspace_id}>
                  {workspace.name}
                </option>
              ))}
            </Select>
          )}
          <Button
            disabled={workspacesFailed || (workspacesReady && workspaces.length === 0)}
            onClick={() => setCreating(true)}
          >
            <Plus className="mr-1.5 h-4 w-4" aria-hidden />
            {t('rooms.newRoom')}
          </Button>
        </div>
      </header>

      <div className="rooms-page__body">
        <aside className="rooms-list" aria-label={t('rooms.listLabel')}>
          <div className="rooms-list__section">{t('rooms.roomsSection')}</div>
          {workspacesFailed ? (
            <div className="rooms-list__placeholder">
              <ErrorBanner error={failureText(workspacesError, t('rooms.workspacesFailed'))} />
              <Button variant="ghost" size="sm" onClick={() => { void refetchWorkspaces(); }}>
                {t('common.retry')}
              </Button>
            </div>
          ) : !workspacesReady || roomsQuery.isLoading ? (
            <div className="rooms-list__placeholder" role="status">{t('common.loading')}</div>
          ) : roomsQuery.isError && rooms.length === 0 ? (
            <div className="rooms-list__placeholder">
              <ErrorBanner error={t('rooms.loadFailed')} />
              <Button variant="ghost" size="sm" onClick={() => { void roomsQuery.refetch(); }}>
                {t('common.retry')}
              </Button>
            </div>
          ) : rooms.length === 0 ? (
            <div className="rooms-list__empty">
              <p className="rooms-list__empty-title">
                {workspaces.length === 0 ? t('rooms.workspaceRequired') : t('rooms.emptyTitle')}
              </p>
              {workspaces.length > 0 && (
                <p className="rooms-list__empty-body">{t('rooms.emptyDescription')}</p>
              )}
            </div>
          ) : (
            rooms.map((room) => (
              <RoomListRow
                key={room.room_id}
                room={room}
                active={room.room_id === selectedRoomId}
                onOpen={() => openRoom(room.room_id)}
              />
            ))
          )}

          <div className="rooms-list__section">{t('rooms.privateSection')}</div>
          {bots.length === 0 ? (
            <div className="rooms-list__empty-body rooms-list__quiet">{t('rooms.privateEmpty')}</div>
          ) : (
            bots.map((bot) => (
              <button
                key={bot.bot_id}
                type="button"
                className="rooms-list__row rooms-list__bot"
                disabled={openingBotId === bot.bot_id}
                onClick={() => { void openPrivateChat(bot); }}
              >
                <span className="rooms-list__name">
                  <BotMark bot={bot} size={16} decorative />
                  <span className="rooms-list__name-text">{bot.name}</span>
                </span>
                <span className="rooms-list__meta">
                  {bot.status === 'paused' ? t('bots.pausedBadge') : t('rooms.privateOpen')}
                </span>
              </button>
            ))
          )}

          <div className="rooms-list__section">
            <span>{t('rooms.botMessagesSection')}</span>
            <Button variant="ghost" size="sm" onClick={() => setBotMessagesOpen(true)}>
              <MessageSquare className="h-3.5 w-3.5" aria-hidden />
              {t('rooms.botMessagesOpen')}
            </Button>
          </div>
        </aside>

        <section className="rooms-detail">
          {selectedRoomId ? (
            <RoomPanel
              key={selectedRoomId}
              roomId={selectedRoomId}
              onClose={() => openRoom(null)}
            />
          ) : (
            <div className="rooms-select">
              <MessagesSquare className="h-8 w-8" aria-hidden />
              <p className="rooms-select__title">{t('rooms.selectTitle')}</p>
              <p className="rooms-select__body">{t('rooms.selectDescription')}</p>
            </div>
          )}
        </section>
      </div>

      {botMessagesOpen && (
        <BotMessagesDrawer
          messages={botMessages.data?.messages ?? []}
          loading={botMessages.isLoading}
          failed={botMessages.isError}
          onClose={() => setBotMessagesOpen(false)}
        />
      )}

      {creating && (
        <CreateRoomDialog
          workspaces={workspaces}
          initialWorkspaceId={workspaceId}
          maxBots={maxBots}
          onClose={() => setCreating(false)}
          onCreated={(room) => {
            setCreating(false);
            setWorkspaceChoice(room.workspace_id);
            openRoom(room.room_id);
          }}
        />
      )}
    </div>
  );
}
