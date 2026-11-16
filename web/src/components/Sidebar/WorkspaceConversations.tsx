/**
 * A workspace's conversations, rendered inside its row in the navigation tree.
 *
 * Three sections, in the order a team reads: the workspace's group chats, its
 * bots, then the threads themselves — scheduled-task runs and ordinary chats —
 * as compact rows. A bot's direct chat is its row, not a second thread entry;
 * the row's second line names the work the bot last did instead of repeating
 * its own name, which is what a missing title fallback produced. The thread
 * row (rename, share, pin) is drawn by the caller so this list stays the only
 * history.
 */
import { Fragment, useMemo, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { BotInfo } from '@/api/bots';
import type { RoomInfo } from '@/api/rooms';
import { useBots } from '@/hooks/useBots';
import { useRooms } from '@/hooks/useRooms';
import { BotMark } from '@/components/bots/BotMark';
import { Loader } from '@/components/ui/loader';
import { RoomAvatar } from '@/pages/Rooms/components/RoomAvatar';
import { useThreadFlags } from '@/lib/threadLifecycle/store';
import { buildBotPairs } from '@/pages/Rooms/botInbox';
import { useBotInbox } from '@/pages/Rooms/useBotInbox';
import { createThreadWithTitle } from '@/pages/ChatAgent/utils/api/threads';
import {
  buildConversationItems,
  formatActivity,
  timeOf,
  titleWithoutRunDate,
  type ConversationItem,
  type ConversationThread,
} from './conversations';
import './ConversationSections.css';

const EMPTY_ROOMS: RoomInfo[] = [];
const EMPTY_BOTS: BotInfo[] = [];
const EMPTY_THREADS: ConversationThread[] = [];

type RoomItem = Extract<ConversationItem, { kind: 'room' }>;
type BotItem = Extract<ConversationItem, { kind: 'bot' }>;
type ThreadItem = Extract<ConversationItem, { kind: 'thread' }>;
/** An entity this list draws as its own row: a room or a bot. */
type EntityItem = RoomItem | BotItem;
type NonThreadItem = Exclude<ConversationItem, { kind: 'thread' }>;

function plainPreview(text: string | null | undefined): string {
  return (text ?? '')
    .replace(/[#>*_`[\]()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120);
}

/**
 * The stamp a row sorts and reads by. A bot moves when its newest thread does,
 * not only when its private chat does, so a scheduled run that landed in a
 * separate thread still raises the bot row above quieter ones.
 */
function activityOf(item: EntityItem, latestByBot: Map<string, ConversationThread>): number {
  if (item.kind === 'bot') {
    return Math.max(item.activity, timeOf(latestByBot.get(item.bot.bot_id)?.updated_at));
  }
  return item.activity;
}

/**
 * The run state a bot's own chat carries beside its row — the same language
 * the thread rows use: a spinner while it works, a ring when it waits on the
 * reader, a dot when a finished run is still unseen.
 */
function ConversationSignal({ threadId }: { threadId: string }) {
  const { t } = useTranslation();
  const { isRunning, needsInput, isUnseen } = useThreadFlags(threadId);
  if (isRunning) {
    return (
      <Loader
        size={12}
        label={t('chat.taskCard.statusRunning')}
        className="workspace-conversations__signal"
      />
    );
  }
  if (needsInput) {
    return (
      <span
        className="workspace-conversations__signal-ring"
        role="img"
        aria-label={t('nav.threadNeedsInput')}
      />
    );
  }
  if (isUnseen) {
    return (
      <span
        className="workspace-conversations__signal-dot"
        role="img"
        aria-label={t('nav.threadUnseen')}
      />
    );
  }
  return null;
}

/** One room or bot row: a 36px face, the name, one muted line, the recency. */
function ConversationRow({
  item,
  name,
  preview,
  avatar,
  when,
  onOpen,
}: {
  item: EntityItem;
  name: string;
  preview: string;
  avatar: ReactNode;
  when: string;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      data-nav-key={item.key}
      className="workspace-conversations__row"
      onClick={onOpen}
    >
      {avatar}
      <span className="workspace-conversations__body">
        <span className="workspace-conversations__name">{name}</span>
        {preview && (
          <span className="workspace-conversations__preview">{preview}</span>
        )}
      </span>
      {item.kind === 'bot' && item.thread && (
        <ConversationSignal threadId={item.thread.thread_id} />
      )}
      <span className="workspace-conversations__when">{when}</span>
    </button>
  );
}

export function WorkspaceConversations({
  workspaceId,
  threads = EMPTY_THREADS,
  onNavigate,
  renderThread,
  footer = null,
}: {
  workspaceId: string;
  /** The workspace's loaded threads: bot primaries, and ordinary chats. */
  threads?: ConversationThread[];
  onNavigate?: () => void;
  /** An ordinary thread, drawn with the nav row's actions. */
  renderThread?: (thread: ConversationThread) => ReactNode;
  /** Sits under the sections, inside the same inset (show more). */
  footer?: ReactNode;
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
  // Bot-to-bot exchanges are not conversation entries: they open from the
  // delivered message in a bot chat, where the reader meets them.
  const items = useMemo(
    () => buildConversationItems(rooms, bots, pairs, threads)
      .filter((item) => item.kind !== 'pair'),
    [rooms, bots, pairs, threads],
  );

  // The newest thread per bot: a bot row's second line names the work that bot
  // last did, so five bots never read as five copies of their own names.
  const latestByBot = useMemo(() => {
    const latest = new Map<string, ConversationThread>();
    for (const thread of threads) {
      if (typeof thread.bot_id !== 'string') continue;
      const previous = latest.get(thread.bot_id);
      if (!previous || timeOf(thread.updated_at) >= timeOf(previous.updated_at)) {
        latest.set(thread.bot_id, thread);
      }
    }
    return latest;
  }, [threads]);

  const groups = useMemo(() => {
    const roomRows = items.filter((item): item is RoomItem => item.kind === 'room');
    const botRows = items.filter((item): item is BotItem => item.kind === 'bot');
    const threadRows = items.filter((item): item is ThreadItem => item.kind === 'thread');
    roomRows.sort((a, b) => activityOf(b, latestByBot) - activityOf(a, latestByBot));
    botRows.sort((a, b) => activityOf(b, latestByBot) - activityOf(a, latestByBot));
    return { rooms: roomRows, bots: botRows, threads: threadRows };
  }, [items, latestByBot]);

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

  const open = (item: NonThreadItem) => {
    if (item.kind === 'room') openRoom(item.room.room_id);
    else if (item.kind === 'pair') openExchange(item.pair.key);
    else void openBot(item.bot.bot_id);
  };

  const label = (item: NonThreadItem) => {
    if (item.kind === 'room') return item.room.name;
    if (item.kind === 'pair') return `${item.pair.left.name} ⇄ ${item.pair.right.name}`;
    return item.bot.name;
  };

  const preview = (item: NonThreadItem) => {
    if (item.kind === 'room') {
      return plainPreview(item.room.preview) || t('rooms.previewEmpty');
    }
    if (item.kind === 'pair') {
      return plainPreview(item.pair.messages.at(-1)?.content) || t('rooms.previewEmpty');
    }
    const name = item.bot.name?.trim();
    const latest = latestByBot.get(item.bot.bot_id)?.title?.trim()
      || item.thread?.title?.trim();
    if (latest && latest !== name) return titleWithoutRunDate(latest);
    // No second line is cleaner than repeating the bot's name: the row itself
    // already opens its private chat.
    return item.bot.status === 'paused' ? t('bots.pausedBadge') : '';
  };

  const avatar = (item: NonThreadItem) => {
    if (item.kind === 'room') {
      return <RoomAvatar members={item.room.members ?? []} size={36} />;
    }
    if (item.kind === 'pair') {
      return (
        <span className="workspace-conversations__faces" aria-hidden>
          <BotMark bot={item.pair.left} size={18} decorative />
          <BotMark bot={item.pair.right} size={18} decorative />
        </span>
      );
    }
    return <BotMark bot={item.bot} size={36} decorative />;
  };

  const rosterLoading = roomsQuery.isLoading || botsQuery.isLoading;

  return (
    <div className="workspace-conversations" aria-label={t('conversations.title')}>
      {items.length === 0 && rosterLoading ? (
        <div className="workspace-conversations__quiet" role="status">
          {t('common.loading')}
        </div>
      ) : items.length === 0 ? (
        <div className="workspace-conversations__quiet">{t('nav.noConversations')}</div>
      ) : (
        <>
          {groups.rooms.length > 0 && (
            <section
              className="workspace-conversations__group"
              aria-label={t('conversations.roomsSection')}
            >
              <div className="workspace-conversations__section">
                {t('conversations.roomsSection')}
              </div>
              {groups.rooms.map((item) => (
                <ConversationRow
                  key={item.key}
                  item={item}
                  name={label(item)}
                  preview={preview(item)}
                  avatar={avatar(item)}
                  when={formatActivity(activityOf(item, latestByBot))}
                  onOpen={() => open(item)}
                />
              ))}
            </section>
          )}

          {groups.bots.length > 0 && (
            <section
              className="workspace-conversations__group"
              aria-label={t('conversations.botsSection')}
            >
              <div className="workspace-conversations__section">
                {t('conversations.botsSection')}
              </div>
              {groups.bots.map((item) => (
                <ConversationRow
                  key={item.key}
                  item={item}
                  name={label(item)}
                  preview={preview(item)}
                  avatar={avatar(item)}
                  when={formatActivity(activityOf(item, latestByBot))}
                  onOpen={() => open(item)}
                />
              ))}
            </section>
          )}

          {groups.threads.length > 0 && (
            <section
              className="workspace-conversations__group"
              aria-label={t('conversations.threadsSection')}
            >
              <div className="workspace-conversations__section">
                {t('conversations.threadsSection')}
              </div>
              {groups.threads.map((item) => (
                <Fragment key={item.key}>{renderThread?.(item.thread)}</Fragment>
              ))}
            </section>
          )}

          {footer}
        </>
      )}
    </div>
  );
}
