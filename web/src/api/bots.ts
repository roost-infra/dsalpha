/**
 * Bot management endpoints.
 *
 * A bot is the identity a turn answers as: it names the speaker and fixes the
 * model and approval surface for that thread's turns. It belongs to one
 * workspace, which stays the unit of sandbox, files and workspace memory, so
 * a bot never moves between workspaces. The Home bot (the user's Chief of
 * Staff) is derived and created lazily by the server, so this client reads it
 * from the list but never creates or deletes it.
 */
import { api } from '@/api/client';
import { getAuthHeaders } from '@/lib/authToken';

/** A workspace analyst, or the derived Home bot. Only an analyst is created here. */
export type BotRole = 'analyst' | 'chief_of_staff';

/** A paused bot keeps its threads readable but refuses to answer. */
export type BotStatus = 'active' | 'paused';

/** The four approval levels the server accepts, least autonomous first. */
export type BotApproval = 'ask' | 'edits' | 'auto' | 'full';

/** One bot as the API returns it. */
export interface BotInfo {
  bot_id: string;
  user_id: string;
  workspace_id: string;
  name: string;
  role: BotRole;
  persona: string;
  avatar: Record<string, unknown>;
  provider: string | null;
  model: string | null;
  skills: string[];
  tools_allow: string[];
  tools_deny: string[];
  approval: BotApproval;
  memory_scopes: string[];
  status: BotStatus;
  primary_thread_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** `GET /api/v1/bots`: one answer for every workspace when none is named. */
export interface BotListResponse {
  bots: BotInfo[];
  /** The server's per-workspace cap, for the create dialog to state. */
  max_bots: number;
}

/** The body of `POST /api/v1/bots`. */
export interface BotCreateInput {
  workspace_id: string;
  name: string;
  /** Only an analyst can be made by hand; the Chief of Staff is derived. */
  role?: 'analyst';
  persona?: string;
  avatar?: Record<string, unknown>;
  provider?: string | null;
  model?: string | null;
  skills?: string[];
  tools_allow?: string[];
  tools_deny?: string[];
  approval?: BotApproval;
  memory_scopes?: string[];
}

/** The body of `PATCH /api/v1/bots/{bot_id}`; an absent field is left alone. */
export type BotUpdateInput = Partial<
  Pick<
    BotInfo,
    | 'name'
    | 'persona'
    | 'avatar'
    | 'provider'
    | 'model'
    | 'skills'
    | 'tools_allow'
    | 'tools_deny'
    | 'approval'
    | 'memory_scopes'
    | 'status'
  >
>;

/** `DELETE /api/v1/bots/{bot_id}`: a soft delete; the row stays auditable. */
export interface BotDeleteResponse {
  ok: boolean;
  bot_id: string;
}

/** Every live bot, or one workspace's when `workspaceId` is named. */
export async function getBots(workspaceId: string | null = null): Promise<BotListResponse> {
  const { data } = await api.get<BotListResponse>(
    '/api/v1/bots',
    workspaceId ? { params: { workspace_id: workspaceId } } : undefined,
  );
  return data;
}

export async function getBot(botId: string): Promise<BotInfo> {
  const { data } = await api.get<BotInfo>(`/api/v1/bots/${encodeURIComponent(botId)}`);
  return data;
}

export async function createBot(input: BotCreateInput): Promise<BotInfo> {
  const { data } = await api.post<BotInfo>('/api/v1/bots', input);
  return data;
}

export async function updateBot(botId: string, patch: BotUpdateInput): Promise<BotInfo> {
  const { data } = await api.patch<BotInfo>(`/api/v1/bots/${encodeURIComponent(botId)}`, patch);
  return data;
}

export async function deleteBot(botId: string): Promise<BotDeleteResponse> {
  const { data } = await api.delete<BotDeleteResponse>(`/api/v1/bots/${encodeURIComponent(botId)}`);
  return data;
}


/** One bot-to-bot message, as the room page's feed lists it. */
export interface BotMessageInfo {
  message_id: string;
  from_type: 'bot' | 'user' | string;
  from_id: string;
  from_name: string | null;
  to_bot_id: string;
  to_name: string;
  kind: string;
  content: string;
  status: string;
  created_at: string | null;
  delivered_at: string | null;
}

export interface BotMessageListResponse {
  messages: BotMessageInfo[];
}

/** Recent bot-to-bot messages for the caller, optionally one workspace. */
export async function getBotMessages(
  workspaceId: string | null = null,
  limit = 50,
): Promise<BotMessageListResponse> {
  const { data } = await api.get<BotMessageListResponse>('/api/v1/bots/messages', {
    params: { ...(workspaceId ? { workspace_id: workspaceId } : {}), limit },
  });
  return data;
}


/** Deleted or malformed frame from the bot inbox tail. */
export class BotMessagesStreamError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'BotMessagesStreamError';
  }
}

/** Tail the bot inbox over SSE from an ISO cursor (null starts at now). */
export function streamBotMessages(
  workspaceId: string | null,
  after: string | null,
  handlers: { onMessage: (message: BotMessageInfo) => void; onClose?: (error: Error | null) => void },
): () => void {
  const controller = new AbortController();
  let stopped = false;
  const finish = (error: Error | null) => {
    if (stopped) return;
    stopped = true;
    handlers.onClose?.(error);
  };

  const run = async () => {
    try {
      const auth = await getAuthHeaders();
      const params = new URLSearchParams();
      if (workspaceId) params.set('workspace_id', workspaceId);
      if (after) params.set('after', after);
      const response = await fetch(`/api/v1/bots/messages/stream?${params.toString()}`, {
        headers: { Accept: 'text/event-stream', ...auth },
        signal: controller.signal,
      });
      if (!response.ok) throw new BotMessagesStreamError(`HTTP ${response.status}`, response.status);
      const reader = response.body?.getReader();
      if (!reader) throw new Error('The bot inbox stream had no body.');
      const decoder = new TextDecoder();
      let buffered = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffered += decoder.decode(value, { stream: true });
        let newline = buffered.indexOf('\n');
        while (newline !== -1) {
          const line = buffered.slice(0, newline).replace(/\r$/, '');
          buffered = buffered.slice(newline + 1);
          newline = buffered.indexOf('\n');
          if (!line.startsWith('data:')) continue;
          try {
            handlers.onMessage(JSON.parse(line.slice(5).trim()) as BotMessageInfo);
          } catch {
            // A malformed frame is not worth tearing the tail down for.
          }
        }
      }
      finish(null);
    } catch (error) {
      finish(controller.signal.aborted ? null : error instanceof Error ? error : new Error('The bot inbox stream failed.'));
    }
  };
  void run();
  return () => { stopped = true; controller.abort(); };
}
