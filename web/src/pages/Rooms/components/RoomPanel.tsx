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
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Archive, ArrowLeft, Crown, Info, Plus, Send, X } from 'lucide-react';
import type { RoomLogEntry, RoomMemberInfo, RoomResponder, RoomView } from '@/api/rooms';
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
import Markdown from '@/pages/ChatAgent/components/Markdown';
import { readWorkspaceFile } from '@/pages/ChatAgent/utils/api/files';
import type { OpenFileHandler } from '@/pages/ChatAgent/utils/fileLocation';
import { responderLabelKey } from '../roomsCopy';
import { RoomAvatar } from './RoomAvatar';
import { failureText } from '@/lib/failureText';

/** Whether a log row is the room talking, not a member. Status rows are the
 *  round's own record ("skipped", "could not answer") and are drawn as notices,
 *  not as anyone's message. */
function isStatusRow(entry: RoomLogEntry): boolean {
  return entry.sender_type === 'system' || entry.kind !== 'message';
}

function dayKey(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toDateString();
}

function dayLabel(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  });
}

function LogRow({
  entry,
  members,
  onOpenFile,
}: {
  entry: RoomLogCacheEntry;
  members: Map<string, RoomMemberInfo>;
  onOpenFile: OpenFileHandler;
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
      {!isUser && (
        <span className="rooms-log__lead">
          <BotMark bot={member ?? { name: sender }} size={22} decorative />
        </span>
      )}
      <div className="rooms-log__content">
        <span className="rooms-log__sender">{sender}</span>
        <div className="rooms-log__bubble rooms-log__bubble--markdown">
          <Markdown content={entry.content} variant="chat" onOpenFile={onOpenFile} />
        </div>
      </div>
    </div>
  );
}

/** A workspace HTML artifact the room opened: rendered in a right-side drawer,
 *  sandboxed so its scripts cannot reach the app. */
function RoomHtmlArtifact({
  workspaceId,
  path,
  onClose,
}: {
  workspaceId: string;
  path: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [content, setContent] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setContent(null);
    setFailed(false);
    readWorkspaceFile(workspaceId, path)
      .then((data: { content?: string }) => {
        if (live) setContent(data.content ?? '');
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => { live = false; };
  }, [workspaceId, path]);

  return (
    <aside className="rooms-artifact" role="dialog" aria-modal="true" aria-label={path}>
      <header className="rooms-artifact__header">
        <span className="rooms-artifact__path" title={path}>{path}</span>
        <Button variant="ghost" size="icon" aria-label={t('common.close')} onClick={onClose}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </header>
      {failed ? (
        <div className="rooms-artifact__state" role="status">{t('rooms.failed')}</div>
      ) : content === null ? (
        <div className="rooms-artifact__state" role="status">{t('common.loading')}</div>
      ) : (
        <iframe
          className="rooms-artifact__frame"
          title={path}
          sandbox="allow-scripts allow-forms allow-popups allow-modals"
          srcDoc={content}
        />
      )}
    </aside>
  );
}

/** A member chip: its role, whether it hosts, whether it is paused, and the
 *  remove control. The host keeps its place — the room row still names it, and
 *  a host that is also a member speaks first. */
function MemberChip({
  member,
  isHost,
  removable,
  onMakeHost,
  onRemove,
}: {
  member: RoomMemberInfo;
  isHost: boolean;
  /** A host keeps its place, and an archived room takes no edits. */
  removable: boolean;
  onMakeHost: () => void;
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
      {removable && !isHost && (
        <button
          type="button"
          className="rooms-member__make-host"
          aria-label={t('rooms.makeHostNamed', { name: member.name })}
          title={t('rooms.makeHost')}
          onClick={onMakeHost}
        >
          <Crown className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
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
  // The tail must not open before the log page fixes the cursor: at 0 it
  // would replay the room's whole history it is about to render anyway.
  const cursorKnown = !!room && logQuery.data !== undefined;
  const {
    round,
    live,
    connectedOnce,
    error: streamError,
    retry: retryStream,
  } = useRoomStream(roomId, lastSeq, cursorKnown);
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
  // The latest action's refusal, not whichever mutation happens to still hold
  // an error: a later successful write clears it.
  const [actionFailure, setActionFailure] = useState<string | null>(null);
  const [unseen, setUnseen] = useState(false);
  const [htmlArtifact, setHtmlArtifact] = useState<{ workspaceId: string; path: string } | null>(null);
  const atBottomRef = useRef(true);
  const logRef = useRef<HTMLDivElement>(null);

  const fail = (error: unknown) => setActionFailure(failureText(error, t('rooms.failed')));
  const clearFailure = () => setActionFailure(null);
  // A room reply can link a workspace file. HTML opens in the side drawer; any
  // other file opens through the authenticated download route.
  const openFile: OpenFileHandler = (path, workspaceId) => {
    const ws = workspaceId || room?.workspace_id;
    if (!ws) return;
    if (/\.html?$/i.test(path)) {
      setHtmlArtifact({ workspaceId: ws, path });
      return;
    }
    window.open(
      `/api/v1/workspaces/${encodeURIComponent(ws)}/files/download?path=${encodeURIComponent(path)}`,
      '_blank',
      'noopener,noreferrer',
    );
  };

  const members = useMemo(() => new Map((room?.members ?? []).map((member) => [member.bot_id, member])), [room?.members]);
  const availableBots = useMemo(() => {
    const membersInRoom = new Set((room?.members ?? []).map((member) => member.bot_id));
    return (botsQuery.data?.bots ?? []).filter((bot) => !membersInRoom.has(bot.bot_id));
  }, [botsQuery.data, room?.members]);
  const maxBots = botsQuery.data?.max_bots ?? 12;
  const atMemberCap = (room?.members.length ?? 0) >= maxBots;


  // The log is a transcript: new rows arrive in view only while the reader is
  // already at the bottom; otherwise they wait behind the jump affordance.
  // A room switch starts a fresh transcript at its bottom.
  const entryCount = entries.length;
  useEffect(() => {
    atBottomRef.current = true;
    setUnseen(false);
  }, [roomId]);
  useEffect(() => {
    const element = logRef.current;
    if (!element) return;
    if (atBottomRef.current) element.scrollTop = element.scrollHeight;
    else if (entryCount > 0) setUnseen(true);
  }, [entryCount, roomId]);
  const onLogScroll = () => {
    const element = logRef.current;
    if (!element) return;
    const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 24;
    atBottomRef.current = atBottom;
    if (atBottom) setUnseen(false);
  };
  const jumpToLatest = () => {
    const element = logRef.current;
    if (element) element.scrollTop = element.scrollHeight;
    atBottomRef.current = true;
    setUnseen(false);
  };

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
  const submitMessage = () => {
    const content = draft.trim();
    if (!content || archived || sendMessage.isPending) return;
    clearFailure();
    setDraft('');
    sendMessage.mutate(
      { roomId, content },
      {
        // A refused send puts the text back where the reader left it, and the
        // refusal is this action's, not whichever mutation errored last.
        onError: (error) => {
          setDraft((current) => current || content);
          fail(error);
        },
      },
    );
  };

  const submitBulletin = () => {
    clearFailure();
    updateRoom.mutate(
      { roomId, patch: { bulletin: (bulletinDraft ?? '').trim() } },
      { onSuccess: () => { setBulletinDraft(null); clearFailure(); }, onError: fail },
    );
  };

  // The log draws a date separator whenever the calendar day changes.
  let lastDay = '';

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
        <RoomAvatar members={room.members} size={36} />
        <div className="rooms-panel__heading">
          <h2 className="rooms-panel__title">{room.name}</h2>
          <div className="rooms-panel__sub">
            <span>{t('rooms.membersCount', { count: room.members.length })}</span>
            <span>{t(responderLabelKey(room.responder))}</span>
            <span
              className={streamError ? 'rooms-live is-error' : live ? 'rooms-live is-live' : 'rooms-live'}
              data-testid="room-live"
            >
              <span className="rooms-live__dot" aria-hidden />
              {streamError
                ? t('rooms.streamError')
                : live
                  ? t('rooms.live')
                  : connectedOnce
                    ? t('rooms.reconnecting')
                    : t('rooms.connecting')}
            </span>
            {streamError && (
              <Button variant="ghost" size="sm" onClick={retryStream}>{t('common.retry')}</Button>
            )}
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
              clearFailure();
              // The value is the responder as the server stores it, including a
              // `member:<id>` set elsewhere: never fold that to "everyone".
              updateRoom.mutate(
                { roomId, patch: { responder: event.target.value as RoomResponder } },
                { onSuccess: clearFailure, onError: fail },
              );
            }}
          >
            <option value="everyone">{t('rooms.responder.everyone')}</option>
            <option value="mentions">{t('rooms.responder.mentions')}</option>
            {/* A single-member responder set by an older client keeps its value
                drawn rather than snapping the select to the wrong option, and
                its option names the bot it keeps. */}
            {room.responder !== 'everyone' && room.responder !== 'mentions' && (
              <option value={room.responder}>
                {(() => {
                  const member = members.get(room.responder.slice('member:'.length));
                  return member
                    ? t('rooms.responder.singleNamed', { name: member.name })
                    : t('rooms.responder.single');
                })()}
              </option>
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
            onMakeHost={() => {
              clearFailure();
              updateRoom.mutate(
                { roomId, patch: { host_bot_id: member.bot_id } },
                { onSuccess: clearFailure, onError: fail },
              );
            }}
            onRemove={() => {
              clearFailure();
              removeMember.mutate(
                { roomId, botId: member.bot_id },
                { onSuccess: clearFailure, onError: fail },
              );
            }}
          />
        ))}
        {!archived && (
          <span className="rooms-member-add">
            {botsQuery.isError ? (
              <>
                <span className="rooms-member-add__empty">{t('rooms.membersError')}</span>
                <Button variant="ghost" size="sm" onClick={() => { void botsQuery.refetch(); }}>
                  {t('common.retry')}
                </Button>
              </>
            ) : botsQuery.isLoading ? (
              <span className="rooms-member-add__empty" role="status">{t('rooms.membersLoading')}</span>
            ) : atMemberCap ? (
              <span className="rooms-member-add__empty">{t('rooms.memberCap', { max: maxBots })}</span>
            ) : availableBots.length > 0 ? (
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
                    clearFailure();
                    addMember.mutate(
                      { roomId, botId: addBotId },
                      {
                        onSuccess: () => { setAddBotId(''); clearFailure(); },
                        onError: fail,
                      },
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

      {(editingBulletin && !archived ? (
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
          {!archived && (
            <button
              type="button"
              className="rooms-panel__bulletin-edit"
              onClick={() => setBulletinDraft(room.bulletin)}
            >
              {t('rooms.bulletinEdit')}
            </button>
          )}
        </div>
      ) : !archived ? (
        <div className="rooms-panel__bulletin rooms-panel__bulletin--empty">
          <button
            type="button"
            className="rooms-panel__bulletin-edit"
            onClick={() => setBulletinDraft('')}
          >
            {t('rooms.bulletinAdd')}
          </button>
        </div>
      ) : null)}

      <div
        className="rooms-panel__log"
        role="log"
        aria-label={t('rooms.logLabel')}
        ref={logRef}
        onScroll={onLogScroll}
      >
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
          entries.map((entry) => {
            const day = dayKey(entry.created_at);
            const showDay = Boolean(day) && day !== lastDay;
            if (showDay) lastDay = day;
            return (
              <Fragment key={entry.pending ? `pending-${entry.seq}` : entry.seq}>
                {showDay && <div className="rooms-log__day">{dayLabel(entry.created_at)}</div>}
                <LogRow
                  entry={entry}
                  members={members}
                  onOpenFile={openFile}
                />
              </Fragment>
            );
          })
        )}
      </div>

      <p className="rooms-ai-disclaimer">{t('chat.aiDisclaimer')}</p>

      {unseen && (
        <button
          type="button"
          onClick={jumpToLatest}
          data-testid="room-new-messages"
          className="mx-auto -mt-10 mb-2 relative z-10 rounded-full border px-3 py-1 text-xs"
          style={{
            backgroundColor: 'var(--color-bg-elevated)',
            borderColor: 'var(--color-border-muted)',
            color: 'var(--color-text-secondary)',
          }}
        >
          {t('rooms.newMessages')}
        </button>
      )}

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
        <div className="rooms-panel__archived" role="status">
          {t('rooms.archivedNotice')}
          <Button
            variant="ghost"
            size="sm"
            disabled={updateRoom.isPending}
            onClick={() => {
              clearFailure();
              updateRoom.mutate(
                { roomId, patch: { status: 'active' } },
                { onSuccess: clearFailure, onError: fail },
              );
            }}
          >
            {t('rooms.restoreRoom')}
          </Button>
        </div>
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

      {htmlArtifact && (
        <RoomHtmlArtifact
          workspaceId={htmlArtifact.workspaceId}
          path={htmlArtifact.path}
          onClose={() => setHtmlArtifact(null)}
        />
      )}
    </div>
  );
}
