/**
 * The bot-to-bot inbox as pair conversations.
 *
 * ``bot_messages`` is one row per send; a reader thinks in pairs ("A ⇄ B"),
 * so the room rail groups the rows by the two bot ids, newest pair first.
 * A pair's left side is whoever spoke first, which is how the exchange opens.
 */
import type { BotInfo, BotMessageInfo } from '@/api/bots';

export interface PairBot {
  bot_id: string;
  name: string;
  avatar?: Record<string, unknown>;
}

export interface BotPair {
  /** The unordered pair's stable key (the two bot ids, sorted). */
  key: string;
  left: PairBot;
  right: PairBot;
  /** Oldest first, the order the exchange reads. */
  messages: BotMessageInfo[];
}

function timeOf(message: BotMessageInfo): number {
  const parsed = message.created_at ? Date.parse(message.created_at) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

function pairKey(a: string, b: string): string {
  return [a, b].sort().join('|');
}

function pairBot(
  botId: string,
  name: string | null,
  bots: Map<string, BotInfo>,
): PairBot {
  const known = bots.get(botId);
  return known
    ? { bot_id: known.bot_id, name: known.name, avatar: known.avatar }
    : { bot_id: botId, name: name || botId };
}

export function buildBotPairs(
  messages: BotMessageInfo[],
  bots: Map<string, BotInfo>,
): BotPair[] {
  const pairs = new Map<string, BotPair>();
  const ordered = [...messages].sort((a, b) => timeOf(a) - timeOf(b));
  for (const message of ordered) {
    if (message.from_type !== 'bot') continue;
    if (message.from_id === message.to_bot_id) continue;
    const key = pairKey(message.from_id, message.to_bot_id);
    let pair = pairs.get(key);
    if (!pair) {
      pair = {
        key,
        left: pairBot(message.from_id, message.from_name, bots),
        right: pairBot(message.to_bot_id, message.to_name, bots),
        messages: [],
      };
      pairs.set(key, pair);
    }
    pair.messages.push(message);
  }
  return [...pairs.values()].sort(
    (a, b) => timeOf(b.messages.at(-1)!) - timeOf(a.messages.at(-1)!),
  );
}
