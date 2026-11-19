/** Manage guest contacts: mint invite links, accept requests, block peers. */
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Copy, Link2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/select';
import type { BotInfo } from '@/api/bots';
import {
  acceptGuestRequest,
  blockGuestPeer,
  createGuestInvite,
  declineGuestRequest,
  getGuestContacts,
  getGuestRequests,
  listGuestInvites,
  revokeGuestInvite,
  type GuestContact,
} from '@/api/guestDm';

export function GuestDmDialog({
  bots,
  onClose,
}: {
  bots: BotInfo[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [botId, setBotId] = useState(bots[0]?.bot_id ?? '');
  const [minted, setMinted] = useState<{ token: string; url: string | null } | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const invites = useQuery({
    queryKey: ['guest-invites', botId],
    queryFn: () => listGuestInvites(botId),
    enabled: !!botId,
  });
  const requests = useQuery({ queryKey: ['guest-requests'], queryFn: getGuestRequests });
  const contacts = useQuery({ queryKey: ['guest-contacts'], queryFn: () => getGuestContacts() });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['guest-invites'] });
    void queryClient.invalidateQueries({ queryKey: ['guest-requests'] });
    void queryClient.invalidateQueries({ queryKey: ['guest-contacts'] });
    void queryClient.invalidateQueries({ queryKey: ['guest-sent'] });
    void queryClient.invalidateQueries({ queryKey: ['bot-messages'] });
  };
  const run = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await action();
      refresh();
    } finally {
      setBusy(null);
    }
  };

  const contactRow = (contact: GuestContact) => {
    const name = contact.peer_bot_name || contact.peer_bot_id;
    return (
      <li key={`${contact.bot_id}:${contact.peer_bot_id}`} className="rooms-guest-dialog__row">
        <span className="rooms-guest-dialog__name">{name}</span>
        <span className="rooms-guest-dialog__muted">{contact.status}</span>
        {contact.status === 'accepted' && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy === contact.peer_bot_id}
            onClick={() => run(contact.peer_bot_id, () => blockGuestPeer(contact.peer_bot_id, contact.bot_id))}
          >
            {t('rooms.guestBlock')}
          </Button>
        )}
      </li>
    );
  };

  return (
    <div
      className="rooms-guest-dialog"
      role="dialog"
      aria-modal="true"
      aria-label={t('rooms.guestDialogTitle')}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="rooms-guest-dialog__sheet">
        <header className="rooms-guest-dialog__header">
          <span className="rooms-guest-dialog__title"><Link2 className="h-4 w-4" aria-hidden />{t('rooms.guestDialogTitle')}</span>
          <Button variant="ghost" size="icon" aria-label={t('common.close')} onClick={onClose}>
            <X className="h-4 w-4" aria-hidden />
          </Button>
        </header>

        <div className="rooms-guest-dialog__body">
          <section className="rooms-guest-dialog__section">
            <h3>{t('rooms.guestInviteTitle')}</h3>
            {bots.length === 0 ? (
              <p className="rooms-guest-dialog__muted">{t('rooms.privateEmpty')}</p>
            ) : (
              <div className="rooms-guest-dialog__inline">
                <Select value={botId} onChange={(event) => { setBotId(event.target.value); setMinted(null); }}>
                  {bots.map((bot) => <option key={bot.bot_id} value={bot.bot_id}>{bot.name}</option>)}
                </Select>
                <Button
                  disabled={!botId || busy === 'mint'}
                  onClick={() => run('mint', async () => {
                    const invite = await createGuestInvite(botId);
                    setMinted({ token: invite.token, url: invite.url });
                  })}
                >
                  {t('rooms.guestInviteCreate')}
                </Button>
              </div>
            )}
            {minted && (
              <div className="rooms-guest-dialog__link">
                <code>{minted.url ?? minted.token}</code>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    void navigator.clipboard?.writeText(minted.url ?? minted.token);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                  }}
                >
                  <Copy className="mr-1 h-3.5 w-3.5" aria-hidden />{copied ? t('rooms.guestCopied') : t('rooms.guestCopy')}
                </Button>
              </div>
            )}
            {invites.data && invites.data.length > 0 && (
              <ul className="rooms-guest-dialog__list">
                {invites.data.map((invite) => (
                  <li key={invite.invite_id} className="rooms-guest-dialog__row">
                    <span className="rooms-guest-dialog__muted">{invite.invite_id.slice(0, 8)}</span>
                    <span className="rooms-guest-dialog__muted">{invite.status} · {invite.uses}/{invite.max_uses}</span>
                    <Button size="sm" variant="ghost" onClick={() => run(invite.invite_id, () => revokeGuestInvite(invite.invite_id))}>
                      {t('rooms.guestRevoke')}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rooms-guest-dialog__section">
            <h3>{t('rooms.guestRequestsTitle')}</h3>
            {requests.data?.contacts?.length ? (
              <ul className="rooms-guest-dialog__list">
                {requests.data.contacts.map((contact) => (
                  <li key={`${contact.bot_id}:${contact.peer_bot_id}`} className="rooms-guest-dialog__row">
                    <span className="rooms-guest-dialog__name">{contact.peer_bot_name || contact.peer_bot_id}</span>
                    <span className="rooms-guest-dialog__muted">{t('rooms.guestPending')}</span>
                    <Button
                      size="sm"
                      disabled={busy === contact.peer_bot_id}
                      onClick={() => run(contact.peer_bot_id, () => acceptGuestRequest(contact.peer_bot_id, contact.bot_id))}
                    >
                      {t('rooms.guestAccept')}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy === contact.peer_bot_id}
                      onClick={() => run(contact.peer_bot_id, () => declineGuestRequest(contact.peer_bot_id, contact.bot_id))}
                    >
                      {t('rooms.guestDecline')}
                    </Button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="rooms-guest-dialog__muted">{t('rooms.guestNoRequests')}</p>
            )}
          </section>

          <section className="rooms-guest-dialog__section">
            <h3>{t('rooms.guestContactsTitle')}</h3>
            {contacts.data?.contacts?.length ? (
              <ul className="rooms-guest-dialog__list">{contacts.data.contacts.map(contactRow)}</ul>
            ) : (
              <p className="rooms-guest-dialog__muted">{t('rooms.guestNoContacts')}</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
