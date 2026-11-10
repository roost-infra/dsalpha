/**
 * One workspace's conversations as a single recency-ordered list.
 *
 * A bot's direct chat, a group chat, a bot-to-bot exchange and an ordinary
 * workspace thread sit at the same level, separated by when they last moved.
 * A bot's primary thread is the bot row, not a second entry. A room member's
 * execution thread never arrives here: the thread list leaves it out.
 */
import type { BotInfo } from '@/api/bots';
import type { RoomInfo } from '@/api/rooms';
import type { BotPair } from '@/pages/Rooms/botInbox';

/** The fields a conversation row needs from a loaded thread. */
export interface ConversationThread {
  thread_id: string;
  title?: string | null;
  updated_at?: string;
  /** Pinned threads stay at the top of the stream; pin is a placement, not activity. */
  is_pinned?: boolean;
}

export type ConversationItem =
  | { kind: 'room'; key: string; activity: number; room: RoomInfo }
  | {
      kind: 'bot';
      key: string;
      activity: number;
      bot: BotInfo;
      /** The bot's private chat, when the loaded page carries it. */
      thread: ConversationThread | null;
    }
  | { kind: 'pair'; key: string; activity: number; pair: BotPair }
  | { kind: 'thread'; key: string; activity: number; thread: ConversationThread };

/** Epoch ms of a timestamp, or 0 for a row that carries none. */
export function timeOf(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function buildConversationItems(
  rooms: RoomInfo[],
  bots: BotInfo[],
  pairs: BotPair[],
  threads: ConversationThread[],
): ConversationItem[] {
  const threadById = new Map(threads.map((thread) => [thread.thread_id, thread]));
  const primaryIds = new Set(
    bots.map((bot) => bot.primary_thread_id).filter((id): id is string => Boolean(id)),
  );
  const items: ConversationItem[] = [];

  for (const room of rooms) {
    items.push({
      kind: 'room',
      key: `room:${room.room_id}`,
      activity: timeOf(room.updated_at ?? room.created_at),
      room,
    });
  }

  for (const bot of bots) {
    const thread = bot.primary_thread_id
      ? threadById.get(bot.primary_thread_id) ?? null
      : null;
    // The thread moves with every turn; the bot row only moves when its
    // settings do, so the thread's stamp is the conversation's activity.
    items.push({
      kind: 'bot',
      key: `bot:${bot.bot_id}`,
      activity: timeOf(thread?.updated_at ?? bot.updated_at),
      bot,
      thread,
    });
  }

  for (const pair of pairs) {
    items.push({
      kind: 'pair',
      key: `pair:${pair.key}`,
      activity: timeOf(pair.messages.at(-1)?.created_at),
      pair,
    });
  }

  for (const thread of threads) {
    if (primaryIds.has(thread.thread_id)) continue;
    items.push({
      kind: 'thread',
      key: `thread:${thread.thread_id}`,
      activity: timeOf(thread.updated_at),
      thread,
    });
  }

  // Pinned chats stay at the top. Otherwise newest first. Array#sort is
  // stable, so equal stamps keep rooms, then bots, then exchanges, then
  // threads in the order they were given.
  const pinned = (item: ConversationItem) =>
    item.kind === 'thread' && item.thread.is_pinned ? 1 : 0;
  return items.sort((a, b) => pinned(b) - pinned(a) || b.activity - a.activity);
}

/** A compact sidebar stamp: the time today, the date before that. */
export function formatActivity(activity: number): string {
  if (!activity) return '';
  const when = new Date(activity);
  const now = new Date();
  if (when.toDateString() === now.toDateString()) {
    return when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return when.toLocaleDateString([], { month: 'numeric', day: 'numeric' });
}
