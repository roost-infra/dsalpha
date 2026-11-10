/**
 * One workspace's conversations as a single recency-ordered list.
 *
 * DS-Bot draws a workspace as one stream: a bot's direct chat and a group
 * chat sit at the same level, separated only by when they last moved. Bot
 * exchanges are conversations too, so they sort into the same stream rather
 * than under a heading of their own.
 */
import type { BotInfo } from '@/api/bots';
import type { RoomInfo } from '@/api/rooms';
import type { BotPair } from '@/pages/Rooms/botInbox';

/** The fields a conversation row needs from a loaded thread. */
export interface ConversationThread {
  thread_id: string;
  title?: string | null;
  updated_at?: string;
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
  | { kind: 'pair'; key: string; activity: number; pair: BotPair };

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

  // Newest first; Array#sort is stable, so equal stamps keep rooms, then
  // bots, then exchanges.
  return items.sort((a, b) => b.activity - a.activity);
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
