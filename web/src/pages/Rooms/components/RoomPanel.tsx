/**
 * One room, opened: its members, its shared log, and the composer that opens a
 * round.
 *
 * Everything drawn here is the server's, except the log's optimistic tail: a
 * send is appended to the log cache before the server answers (so the message
 * never looks lost) and the SSE tail appends the persisted rows as they land.
 * The round line above the composer is the one live signal a reader needs —
 * who is speaking, or that the round is over.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Archive, ArrowLeft, Info, Plus, Send, X } from 'lucide-react';
import { ApiError } from '@/api/client';
import type { RoomLogEntry, RoomMemberInfo, RoomView } from '@/api/rooms';
import { BotMark } from '@/components/bots/BotMark';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ErrorBanner } from '@/components/ui/error-banner';
import { Select } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useBots } from '@/hooks/useBots';
import {
  useAddRoomMember,
  useRemoveRoomMember,
  useRoom,
  useRoomLog,
  useRoomStream,
  useSendRoomMessage,
  useUpdateRoom,
  type RoomLogCacheEntry,
} from '@/hooks/useRooms';
import { responderLabelKey } from '../roomsCopy';

/** The server writes refusals meant for the user; anything else gets ours. */
function failureText(error: unknown, fallback: string): string | null {
  if (!error) return null;
  return error instanceof ApiError && error.message ? error.message : fallback;
}

/** Whether a log row is the room talking, not a member. Status rows are the
 *  round's own record ("skipped", "could not answer") and are drawn as notices,
 *  not as anyone's message. */
function isStatusRow(entry: RoomLogEntry): boolean {
  return entry.sender_type === 'system' || entry.kind !== 'message';
}

function LogRow({
  entry,
  members,
}: {
  entry: RoomLogCacheEntry;
  members: Map<string, RoomMemberInfo>;
}) {
  const { t } = useTranslation();
  if (isStatusRow(entry)) {
    return (
      <div className="rooms-log__status" data-testid="room-log-status" role="note">
        <Info className="h-3 w-3 shrink-0" aria-hidden />
        <span>{entry.content}</span>
      </div>
    );
  }
  const isUser = entry.sender_type === 'user';
  // A member's own row: its mark is on the log line, as on its chip.
  const member = isUser ? undefined : members.get(entry.sender_id);
  const sender = isUser
    ? t('rooms.you')
    : (member?.name ?? t('rooms.unknownSender'));
  return (
    <div
      className={isUser ? 'rooms-log__row rooms-log__row--user' : 'rooms-log__row'}
      data-testid="room-log-message"
      data-sender-type={entry.sender_type}
      data-pending={entry.pending ? 'true' : undefined}
    >
      <span className="rooms-log__sender inline-flex items-center gap-1">
        {!isUser && <BotMark bot={member ?? { name: sender }} size={16} decorative />}
        <span>{sender}</span>
      </span>
      <div className="rooms-log__bubble">{entry.content}</div>
    </div>
  );
}

/** A member chip: its role, whether it hosts, whether it is paused, and the
 *  remove control. The host keeps its place — the room row still names it, and
 *  a host that is also a member speaks first. */
function MemberChip({
  member,
  isHost,
  removable,
  onRemove,
}: {
  member: RoomMemberInfo;
  isHost: boolean;
  /** A host keeps its place, and an archived room takes no edits. */
  removable: boolean;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const paused = member.status === 'paused';
  return (
    <span
      className="rooms-member"
      data-host={isHost || undefined}
      data-paused={paused || undefined}
    >
      <BotMark bot={member} size={20} decorative />
      <span className="rooms-member__name">{member.name}</span>
      <span className="rooms-member__role">
        {t(member.role === 'chief_of_staff' ? 'agents.chiefOfStaff' : 'agents.analyst')}
      </span>
      {isHost && <span className="rooms-member__badge">{t('rooms.hostBadge')}</span>}
      {paused && (
        <span className="rooms-member__badge rooms-member__badge--paused">
          {t('rooms.pausedBadge')}
        </span>
      )}
      {removable && !isHost && (
        <button
          type="button"
          className="rooms-member__remove"
          aria-label={t('rooms.removeMember', { name: member.name })}
          onClick={onRemove}
        >
          <X className="h-3 w-3" aria-hidden />
        </button>
      )}
    </span>
  );
}

function ArchiveRoomDialog({ room, onClose }: { room: RoomView; onClose: () => void }) {
  const { t } = useTranslation();
  const updateRoom = useUpdateRoom();
  const failure = failureText(updateRoom.error, t('rooms.failed'));
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !updateRoom.isPending) onClose(); }}>
      <DialogContent style={{ backgroundColor: 'var(--color-bg-page)', borderColor: 'var(--color-border-muted)' }}>
        <DialogHeader>
          <DialogTitle>{t('rooms.archiveTitle')}</DialogTitle>
          <DialogDescription>
            {t('rooms.archiveDescription', { name: room.name })}
          </DialogDescription>
        </DialogHeader>
        {failure && <ErrorBanner error={failure} />}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={updateRoom.isPending}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="destructive"
            disabled={updateRoom.isPending}
            onClick={() => {
              updateRoom.mutate(
                { roomId: room.room_id, patch: { status: 'archived' } },
                { onSuccess: onClose },
              );
            }}
          >
            {updateRoom.isPending ? t('common.saving') : t('rooms.archiveConfirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function RoomPanel({ roomId, onClose }: { roomId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const roomQuery = useRoom(roomId);
  const room = roomQuery.data;
  const logQuery = useRoomLog(roomId);
  const entries = logQuery.data ?? [];
  const lastSeq = (logQuery.data ?? []).reduce(
    (highest, entry) => (entry.pending ? highest : Math.max(highest, entry.seq)),
    0,
  );
  const { round, live } = useRoomStream(roomId, lastSeq, !!room);
  const botsQuery = useBots(room?.workspace_id ?? null, !!room);
  const sendMessage = useSendRoomMessage();
  const updateRoom = useUpdateRoom();
  const addMember = useAddRoomMember();
  const removeMember = useRemoveRoomMember();

  const [draft, setDraft] = useState('');
  const [addBotId, setAddBotId] = useState('');
  // Null means "not editing"; the draft is seeded from the server's copy when
  // the reader opens the editor, so no effect has to mirror the room into state.
  const [bulletinDraft, setBulletinDraft] = useState<string | null>(null);
  const editingBulletin = bulletinDraft !== null;
  const [archiveOpen, setArchiveOpen] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const members = useMemo(() => new Map((room?.members ?? []).map((member) => [member.bot_id, member])), [room?.members]);
  const availableBots = useMemo(() => {
    const membersInRoom = new Set((room?.members ?? []).map((member) => member.bot_id));
    return (botsQuery.data?.bots ?? []).filter((bot) => !membersInRoom.has(bot.bot_id));
  }, [botsQuery.data, room?.members]);

  // The log is a transcript: new rows should arrive in view, not below it.
  const entryCount = entries.length;
  useEffect(() => {
    const element = logRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [entryCount, roomId]);

  const roundLine = useMemo((): { text: string; member: RoomMemberInfo | null } | null => {
    if (!round) return null;
    if (round.status === 'finished') return { text: t('rooms.round.finished'), member: null };
    if (round.status === 'failed') return { text: t('rooms.round.failed'), member: null };
    if (round.status === 'queued') return { text: t('rooms.round.queued'), member: null };
    const slots = round.slots ?? [];
    const cursor = round.slot_cursor ?? 0;
    if (cursor >= slots.length) return { text: t('rooms.round.wrapUp'), member: null };
    const slot = slots[cursor];
    const member = slot ? members.get(slot.bot_id) ?? null : null;
    const name =
      slot?.name ||
      member?.name ||
      t('rooms.unknownSender');
    return { text: t('rooms.round.speaking', { name }), member };
  }, [round, members, t]);

  if (roomQuery.isLoading) {
    return (
      <div className="rooms-panel" role="status">
        <div className="rooms-panel__placeholder">{t('common.loading')}</div>
      </div>
    );
  }

  if (roomQuery.isError || !room) {
    return (
      <div className="rooms-panel">
        <div className="rooms-panel__placeholder">
          <ErrorBanner error={failureText(roomQuery.error, t('rooms.roomLoadFailed'))} />
          <Button variant="ghost" size="sm" onClick={() => { void roomQuery.refetch(); }}>
            {t('common.retry')}
          </Button>
        </div>
      </div>
    );
  }

  const archived = room.status !== 'active';
  const actionFailure = failureText(
    sendMessage.error ?? updateRoom.error ?? addMember.error ?? removeMember.error,
    t('rooms.failed'),
  );

  const submitMessage = () => {
    const content = draft.trim();
    if (!content || archived || sendMessage.isPending) return;
    setDraft('');
    sendMessage.mutate(
      { roomId, content },
      // A refused send puts the text back where the reader left it.
      { onError: () => setDraft((current) => current || content) },
    );
  };

  const submitBulletin = () => {
    updateRoom.mutate(
      { roomId, patch: { bulletin: (bulletinDraft ?? '').trim() } },
      { onSuccess: () => setBulletinDraft(null) },
    );
  };

  return (
    <div className="rooms-panel">
      <header className="rooms-panel__header">
        <button
          type="button"
          className="rooms-panel__back"
          aria-label={t('rooms.back')}
          onClick={onClose}
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
        </button>
        <div className="rooms-panel__heading">
          <h2 className="rooms-panel__title">{room.name}</h2>
          <div className="rooms-panel__sub">
            <span>{t(responderLabelKey(room.responder))}</span>
            <span className={live ? 'rooms-live is-live' : 'rooms-live'} data-testid="room-live">
              <span className="rooms-live__dot" aria-hidden />
              {live ? t('rooms.live') : t('rooms.reconnecting')}
            </span>
            {archived && <Badge variant="muted">{t('rooms.archivedBadge')}</Badge>}
          </div>
        </div>
        <div className="rooms-panel__actions">
          <Select
            className="rooms-panel__responder"
            aria-label={t('rooms.responder.label')}
            value={room.responder}
            disabled={archived || updateRoom.isPending}
            onChange={(event) => {
              updateRoom.mutate({
                roomId,
                patch: { responder: event.target.value === 'mentions' ? 'mentions' : 'everyone' },
              });
            }}
          >
            <option value="everyone">{t('rooms.responder.everyone')}</option>
            <option value="mentions">{t('rooms.responder.mentions')}</option>
            {/* A single-member responder set by an older client keeps its value
                drawn rather than snapping the select to the wrong option. */}
            {room.responder !== 'everyone' && room.responder !== 'mentions' && (
              <option value={room.responder}>{t('rooms.responder.single')}</option>
            )}
          </Select>
          {!archived && (
            <Button variant="ghost" size="sm" onClick={() => setArchiveOpen(true)}>
              <Archive className="mr-1.5 h-4 w-4" aria-hidden />
              {t('rooms.archiveRoom')}
            </Button>
          )}
        </div>
      </header>

      <div className="rooms-panel__members" role="group" aria-label={t('rooms.members')}>
        {room.members.map((member) => (
          <MemberChip
            key={member.bot_id}
            member={member}
            isHost={member.room_role === 'host' || member.bot_id === room.host_bot_id}
            removable={!archived}
            onRemove={() => removeMember.mutate({ roomId, botId: member.bot_id })}
          />
        ))}
        {!archived && (
          <span className="rooms-member-add">
            {availableBots.length > 0 ? (
              <>
                <Select
                  className="rooms-member-add__select"
                  aria-label={t('rooms.addMember')}
                  value={addBotId}
                  onChange={(event) => setAddBotId(event.target.value)}
                >
                  <option value="">{t('rooms.addMemberPlaceholder')}</option>
                  {availableBots.map((bot) => (
                    <option key={bot.bot_id} value={bot.bot_id}>
                      {bot.name}
                    </option>
                  ))}
                </Select>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!addBotId || addMember.isPending}
                  onClick={() => {
                    addMember.mutate(
                      { roomId, botId: addBotId },
                      { onSuccess: () => setAddBotId('') },
                    );
                  }}
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  {t('rooms.addMember')}
                </Button>
              </>
            ) : (
              <span className="rooms-member-add__empty">{t('rooms.allMembersAdded')}</span>
            )}
          </span>
        )}
      </div>

      {editingBulletin ? (
        <div className="rooms-panel__bulletin rooms-panel__bulletin--editing">
          <Textarea
            aria-label={t('rooms.bulletin')}
            value={bulletinDraft ?? ''}
            onChange={(event) => setBulletinDraft(event.target.value)}
            placeholder={t('rooms.bulletinPlaceholder')}
            rows={2}
            maxLength={2000}
          />
          <div className="rooms-panel__bulletin-actions">
            <Button
              variant="ghost"
              size="sm"
              disabled={updateRoom.isPending}
              onClick={() => setBulletinDraft(null)}
            >
              {t('common.cancel')}
            </Button>
            <Button size="sm" disabled={updateRoom.isPending} onClick={submitBulletin}>
              {updateRoom.isPending ? t('common.saving') : t('rooms.bulletinSave')}
            </Button>
          </div>
        </div>
      ) : room.bulletin ? (
        <div className="rooms-panel__bulletin">
          <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="rooms-panel__bulletin-text">{room.bulletin}</span>
          <button
            type="button"
            className="rooms-panel__bulletin-edit"
            onClick={() => setBulletinDraft(room.bulletin)}
          >
            {t('rooms.bulletinEdit')}
          </button>
        </div>
      ) : (
        <div className="rooms-panel__bulletin rooms-panel__bulletin--empty">
          <button
            type="button"
            className="rooms-panel__bulletin-edit"
            onClick={() => setBulletinDraft('')}
          >
            {t('rooms.bulletinAdd')}
          </button>
        </div>
      )}

      <div className="rooms-panel__log" role="log" aria-label={t('rooms.logLabel')} ref={logRef}>
        {logQuery.isError ? (
          <div className="rooms-panel__placeholder">
            <ErrorBanner error={failureText(logQuery.error, t('rooms.logLoadFailed'))} />
            <Button variant="ghost" size="sm" onClick={() => { void logQuery.refetch(); }}>
              {t('common.retry')}
            </Button>
          </div>
        ) : logQuery.isLoading ? (
          <div className="rooms-panel__placeholder" role="status">{t('common.loading')}</div>
        ) : entries.length === 0 ? (
          <div className="rooms-panel__placeholder">{t('rooms.logEmpty')}</div>
        ) : (
          entries.map((entry) => (
            <LogRow
              key={entry.pending ? `pending-${entry.seq}` : entry.seq}
              entry={entry}
              members={members}
            />
          ))
        )}
      </div>

      {roundLine && (
        <div className="rooms-panel__round" role="status" aria-live="polite" data-testid="room-round-status">
          {roundLine.member
            ? <BotMark bot={roundLine.member} size={16} decorative />
            : <span className="rooms-panel__round-dot" aria-hidden />}
          {roundLine.text}
        </div>
      )}

      {actionFailure && <ErrorBanner error={actionFailure} className="rooms-panel__error" />}

      {archived ? (
        <div className="rooms-panel__archived" role="status">{t('rooms.archivedNotice')}</div>
      ) : (
        <form
          className="rooms-panel__composer"
          onSubmit={(event) => {
            event.preventDefault();
            submitMessage();
          }}
        >
          <Textarea
            aria-label={t('rooms.composer.placeholder')}
            placeholder={t('rooms.composer.placeholder')}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submitMessage();
              }
            }}
            rows={2}
            maxLength={64 * 1024}
            disabled={sendMessage.isPending}
          />
          <Button type="submit" disabled={!draft.trim() || sendMessage.isPending}>
            <Send className="mr-1.5 h-4 w-4" aria-hidden />
            {sendMessage.isPending ? t('rooms.composer.sending') : t('rooms.composer.send')}
          </Button>
        </form>
      )}

      {archiveOpen && <ArchiveRoomDialog room={room} onClose={() => setArchiveOpen(false)} />}
    </div>
  );
}
