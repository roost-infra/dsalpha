import { describe, expect, it } from 'vitest';

import type { BotInfo } from '@/api/bots';
import type { RoomInfo } from '@/api/rooms';
import type { BotPair } from '@/pages/Rooms/botInbox';
import type { Thread } from '@/types/api';
import { buildConversationItems, formatActivity, timeOf } from '../conversations';

function bot(id: string, overrides: Partial<BotInfo> = {}): BotInfo {
  return {
    bot_id: id,
    user_id: 'u',
    workspace_id: 'ws',
    name: id,
    role: 'analyst',
    persona: '',
    avatar: {},
    provider: null,
    model: null,
    skills: [],
    tools_allow: [],
    tools_deny: [],
    approval: 'ask',
    memory_scopes: [],
    status: 'active',
    primary_thread_id: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function room(id: string, overrides: Partial<RoomInfo> = {}): RoomInfo {
  return {
    room_id: id,
    workspace_id: 'ws',
    name: id,
    host_bot_id: null,
    responder: 'everyone',
    bulletin: '',
    status: 'active',
    created_at: null,
    ...overrides,
  };
}

function thread(id: string, updatedAt: string): Thread {
  return { thread_id: id, workspace_id: 'ws', title: `${id} title`, updated_at: updatedAt };
}

function pair(key: string, lastAt: string): BotPair {
  return {
    key,
    left: { bot_id: `${key}-a`, name: 'A' },
    right: { bot_id: `${key}-b`, name: 'B' },
    messages: [
      {
        message_id: `${key}-m`,
        from_type: 'bot',
        from_id: `${key}-a`,
        from_name: 'A',
        to_bot_id: `${key}-b`,
        to_name: 'B',
        kind: 'message',
        content: 'hi',
        status: 'delivered',
        created_at: lastAt,
        delivered_at: null,
      },
    ],
  };
}

describe('buildConversationItems', () => {
  it('mixes rooms, bots and exchanges into one recency-ordered stream', () => {
    const items = buildConversationItems(
      [
        room('older-room', { updated_at: '2026-11-10T10:00:00Z' }),
        room('newer-room', { updated_at: '2026-11-10T12:00:00Z' }),
      ],
      [
        bot('with-thread', { primary_thread_id: 't1' }),
        bot('without-thread', { updated_at: '2026-11-10T09:00:00Z' }),
      ],
      [pair('p', '2026-11-10T13:00:00Z')],
      [thread('t1', '2026-11-10T11:00:00Z')],
    );

    expect(items.map((item) => item.key)).toEqual([
      'pair:p',
      'room:newer-room',
      'bot:with-thread',
      'room:older-room',
      'bot:without-thread',
    ]);
  });

  it("stamps a bot with its private thread's activity and title row", () => {
    const items = buildConversationItems(
      [],
      [bot('b', { primary_thread_id: 't1', updated_at: '2026-11-01T00:00:00Z' })],
      [],
      [thread('t1', '2026-11-10T11:00:00Z')],
    );

    const item = items[0];
    expect(item.kind).toBe('bot');
    if (item.kind !== 'bot') throw new Error('expected a bot row');
    expect(item.thread?.title).toBe('t1 title');
    expect(item.activity).toBe(Date.parse('2026-11-10T11:00:00Z'));
  });

  it('sorts a row with no usable stamp last', () => {
    const items = buildConversationItems(
      [room('no-stamp'), room('stamped', { updated_at: '2026-11-10T10:00:00Z' })],
      [],
      [],
      [],
    );

    expect(items.map((item) => item.key)).toEqual(['room:stamped', 'room:no-stamp']);
  });
});

describe('timeOf / formatActivity', () => {
  it('reads a timestamp and treats a missing or malformed one as none', () => {
    expect(timeOf('2026-11-10T10:00:00Z')).toBe(Date.parse('2026-11-10T10:00:00Z'));
    expect(timeOf(null)).toBe(0);
    expect(timeOf('not a date')).toBe(0);
  });

  it('draws nothing for a row with no stamp', () => {
    expect(formatActivity(0)).toBe('');
  });
});
