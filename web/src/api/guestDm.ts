/**
 * Guest DM: invite-gated messaging with bots owned by other accounts.
 *
 * A receiving owner mints a link for one bot; the sender's first message waits
 * until that owner accepts. Once accepted, the same peer can be messaged by bot
 * id through /contacts/{peer}/send, which is what the conversation composer
 * uses; the invite token is only the first-contact address.
 */
import { api } from '@/api/client';

export interface GuestInviteMinted {
  invite_id: string;
  bot_id: string;
  token: string;
  url: string | null;
  expires_at: string | null;
  max_uses: number;
  uses: number;
  status: string;
}

export interface GuestInvite {
  invite_id: string;
  bot_id: string;
  expires_at: string | null;
  max_uses: number;
  uses: number;
  status: string;
}

export interface GuestContact {
  owner_user_id: string;
  bot_id: string;
  peer_bot_id: string;
  peer_user_id: string;
  status: 'pending' | 'accepted' | 'blocked';
  invite_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  peer_bot_name?: string | null;
  peer_bot_status?: string | null;
}

export interface GuestMessage {
  message_id: string;
  from_type: string;
  from_id: string;
  from_user_id?: string | null;
  from_name?: string | null;
  external?: boolean;
  to_bot_id: string;
  to_name?: string | null;
  to_user_id?: string | null;
  kind: string;
  content: string;
  status: string;
  created_at: string | null;
  delivered_at: string | null;
}

export interface GuestSendResult {
  message_id: string;
  status: string;
  contact_status?: string | null;
  thread_id?: string | null;
}

export interface GuestRequestResult {
  contact_status: string;
  peer_bot_id?: string | null;
  pending_messages?: number;
  failed_messages?: number;
}

export async function getGuestSent(limit = 100): Promise<{ messages: GuestMessage[] }> {
  const { data } = await api.get<{ messages: GuestMessage[] }>('/api/v1/dm/sent', {
    params: { limit },
  });
  return data;
}

export async function getGuestContacts(status?: string): Promise<{ contacts: GuestContact[] }> {
  const { data } = await api.get<{ contacts: GuestContact[] }>('/api/v1/dm/contacts', {
    params: status ? { status } : undefined,
  });
  return data;
}

export async function getGuestRequests(): Promise<{ contacts: GuestContact[] }> {
  const { data } = await api.get<{ contacts: GuestContact[] }>('/api/v1/dm/requests');
  return data;
}

export async function createGuestInvite(
  botId: string,
  expiresInHours = 168,
  maxUses = 1,
): Promise<GuestInviteMinted> {
  const { data } = await api.post<GuestInviteMinted>('/api/v1/dm/invites', {
    bot_id: botId,
    expires_in_hours: expiresInHours,
    max_uses: maxUses,
  });
  return data;
}

export async function listGuestInvites(botId: string): Promise<GuestInvite[]> {
  const { data } = await api.get<GuestInvite[]>('/api/v1/dm/invites', {
    params: { bot_id: botId },
  });
  return data;
}

export async function revokeGuestInvite(inviteId: string): Promise<void> {
  await api.delete(`/api/v1/dm/invites/${encodeURIComponent(inviteId)}`);
}

export async function sendToGuestContact(
  peerBotId: string,
  botId: string,
  content: string,
  kind = 'message',
): Promise<GuestSendResult> {
  const { data } = await api.post<GuestSendResult>(
    `/api/v1/dm/contacts/${encodeURIComponent(peerBotId)}/send`,
    { bot_id: botId, content, kind },
  );
  return data;
}

export async function acceptGuestRequest(
  peerBotId: string,
  botId: string,
): Promise<GuestRequestResult> {
  const { data } = await api.post<GuestRequestResult>(
    `/api/v1/dm/requests/${encodeURIComponent(peerBotId)}/accept`,
    { bot_id: botId },
  );
  return data;
}

export async function declineGuestRequest(
  peerBotId: string,
  botId: string,
): Promise<GuestRequestResult> {
  const { data } = await api.post<GuestRequestResult>(
    `/api/v1/dm/requests/${encodeURIComponent(peerBotId)}/decline`,
    { bot_id: botId },
  );
  return data;
}

export async function blockGuestPeer(
  peerBotId: string,
  botId: string,
): Promise<GuestRequestResult> {
  const { data } = await api.post<GuestRequestResult>(
    `/api/v1/dm/contacts/${encodeURIComponent(peerBotId)}/block`,
    { bot_id: botId },
  );
  return data;
}
