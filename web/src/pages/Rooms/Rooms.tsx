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
import { useTranslation } from 'react-i18next';
import { Bot as BotIcon, MessagesSquare, Plus, UsersRound } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/ui/error-banner';
import { Select } from '@/components/ui/select';
import { useAllWorkspaces } from '@/hooks/useAllWorkspaces';
import { useBots } from '@/hooks/useBots';
import { useRoom, useRooms } from '@/hooks/useRooms';
import type { RoomInfo } from '@/api/rooms';
import type { BotInfo } from '@/api/bots';
import { BotMark } from '@/components/bots/BotMark';
import { createThreadWithTitle } from '@/pages/ChatAgent/utils/api/threads';
import { failureText } from '@/lib/failureText';
import { responderLabelKey } from './roomsCopy';
import CreateRoomDialog from './components/CreateRoomDialog';
import { RoomAvatar } from './components/RoomAvatar';
import { BotExchangePanel } from './components/BotExchangePanel';
import { buildBotPairs } from './botInbox';
import { useBotInbox } from './useBotInbox';
import RoomPanel from './components/RoomPanel';
import './Rooms.css';

const ROOM_READ_KEY = 'langalpha.rooms.read';

function loadReadSeqs(): Record<string, number> {
  try {
    const raw = window.localStorage.getItem(ROOM_READ_KEY);
    return raw ? (JSON.parse(raw) as Record<string, number>) : {};
  } catch {
    return {};
  }
}

function saveReadSeqs(seqs: Record<string, number>): void {
  try {
    window.localStorage.setItem(ROOM_READ_KEY, JSON.stringify(seqs));
  } catch {
    // A full or disabled storage only costs the unread dot, not the room.
  }
}

function RoomListRow({
  room,
  active,
  unread,
  onOpen,
}: {
  room: RoomInfo;
  active: boolean;
  unread: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className={active ? 'rooms-list__row rooms-list__row--room is-active' : 'rooms-list__row rooms-list__row--room'}
      aria-current={active ? 'true' : undefined}
      onClick={onOpen}
    >
      <RoomAvatar members={room.members ?? []} size={34} />
      <span className="rooms-list__body">
        <span className="rooms-list__name">
          <span className="rooms-list__name-text">{room.name}</span>
          {room.status === 'archived' && (
            <Badge variant="muted">{t('rooms.archivedBadge')}</Badge>
          )}
          {unread && !active && <span className="rooms-list__unread" aria-label={t('rooms.unread')} />}
        </span>
        <span className="rooms-list__preview">
          {room.preview?.trim() || t('rooms.previewEmpty')}
        </span>
      </span>
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
  const [exchangeKey, setExchangeKey] = useState<string | null>(() => searchParams.get('exchange'));
  const [openingBotId, setOpeningBotId] = useState<string | null>(null);
  const [readSeqs, setReadSeqs] = useState<Record<string, number>>(loadReadSeqs);
  const markRoomRead = (room: RoomInfo) => {
    if (!room.latest_seq) return;
    setReadSeqs((current) => {
      if ((current[room.room_id] ?? 0) >= room.latest_seq!) return current;
      const next = { ...current, [room.room_id]: room.latest_seq! };
      saveReadSeqs(next);
      return next;
    });
  };

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
  const inbox = useBotInbox(workspaceId);
  const bots = botsQuery.data?.bots ?? [];
  const botsById = useMemo(() => new Map(bots.map((bot) => [bot.bot_id, bot])), [bots]);
  const botPairs = useMemo(() => buildBotPairs(inbox.messages, botsById), [inbox.messages, botsById]);
  const activePair = botPairs.find((pair) => pair.key === exchangeKey) ?? null;
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
    const fromUrl = searchParams.get('exchange');
    if (fromUrl !== exchangeKey) setExchangeKey(fromUrl);
  }, [searchParams, exchangeKey]);

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
    next.delete('exchange');
    setExchangeKey(null);
    setSearchParams(next, { replace: true });
  };

  const changeWorkspace = (nextWorkspaceId: string) => {
    setWorkspaceChoice(nextWorkspaceId);
    openRoom(null);
  };

  // The sidebar navigates an exchange by URL so a deep link can open the pair
  // too; closing it removes the parameter instead of leaving a stale key.
  const chooseExchange = (key: string | null) => {
    setExchangeKey(key);
    const next = new URLSearchParams(searchParams);
    if (key) {
      next.set('exchange', key);
      next.delete('room');
    } else {
      next.delete('exchange');
    }
    setSearchParams(next, { replace: true });
  };

  return (
    <div className={selectedRoomId || activePair ? 'rooms-page rooms-page--detail' : 'rooms-page'}>
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
                unread={(room.latest_seq ?? 0) > (readSeqs[room.room_id] ?? 0)}
                onOpen={() => {
                  markRoomRead(room);
                  openRoom(room.room_id);
                }}
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

          <div className="rooms-list__section">{t('rooms.botMessagesSection')}</div>
          {inbox.isLoading && botPairs.length === 0 ? (
            <div className="rooms-list__empty-body rooms-list__quiet" role="status">
              {t('common.loading')}
            </div>
          ) : botPairs.length === 0 ? (
            <div className="rooms-list__empty-body rooms-list__quiet">{t('rooms.botMessagesEmpty')}</div>
          ) : (
            botPairs.map((pair) => (
              <button
                key={pair.key}
                type="button"
                className={
                  exchangeKey === pair.key
                    ? 'rooms-list__row rooms-list__row--exchange is-active'
                    : 'rooms-list__row rooms-list__row--exchange'
                }
                aria-current={exchangeKey === pair.key ? 'true' : undefined}
                onClick={() => chooseExchange(pair.key)}
              >
                <span className="rooms-exchange__faces" aria-hidden>
                  <BotMark bot={pair.left} size={20} decorative />
                  <BotMark bot={pair.right} size={20} decorative />
                </span>
                <span className="rooms-list__body">
                  <span className="rooms-list__name">
                    <span className="rooms-list__name-text">
                      {pair.left.name} ⇄ {pair.right.name}
                    </span>
                  </span>
                  <span className="rooms-list__preview">
                    {pair.messages.at(-1)?.content.replace(/\s+/g, ' ').trim() || t('rooms.previewEmpty')}
                  </span>
                </span>
              </button>
            ))
          )}
        </aside>

        <section className="rooms-detail">
          {activePair ? (
            <BotExchangePanel
              pair={activePair}
              messages={activePair.messages}
              loading={inbox.isLoading}
              failed={inbox.isError}
              onClose={() => chooseExchange(null)}
            />
          ) : selectedRoomId ? (
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
