/** Merge the two guest-message reads (received inbox + sent) into bot pairs. */
import type { BotMessageInfo } from '@/api/bots';
import type { GuestMessage } from '@/api/guestDm';
import type { BotPair } from './botInbox';

export function mergeBotMessages(
  inbox: BotMessageInfo[],
  sent: GuestMessage[],
): BotMessageInfo[] {
  const seen = new Set<string>();
  const out: BotMessageInfo[] = [];
  for (const message of [...inbox, ...sent]) {
    if (seen.has(message.message_id)) continue;
    seen.add(message.message_id);
    out.push(message as BotMessageInfo);
  }
  return out;
}

/** A pair is a guest conversation when at least one side lives elsewhere. */
export function isGuestPair(pair: BotPair): boolean {
  return pair.messages.some(
    (message) => message.external || message.from_type === 'guest_bot',
  );
}

/** The local bot in a guest pair (the one this account owns). */
export function localSideOf(pair: BotPair, localIds: Set<string>): 'left' | 'right' | null {
  if (localIds.has(pair.left.bot_id)) return 'left';
  if (localIds.has(pair.right.bot_id)) return 'right';
  return null;
}
