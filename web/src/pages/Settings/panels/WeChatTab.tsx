/**
 * WeChat channel binding — scan the QR with WeChat to attach a bot.
 *
 * The QR payload is a liteapp URL, not an image, so it is rendered here rather
 * than <img src>. The status endpoint is a long poll on the vendor side, so a
 * "wait" answer is the normal case and polling simply continues.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { api } from '@/api/client';
import { useTranslation } from 'react-i18next';

type Status = {
  enabled: boolean;
  bound: boolean;
  account_id?: string;
  agent_mode?: string;
  workspace_id?: string | null;
  running?: boolean;
  peers?: number;
};

type QrPayload = { qr_value: string; image_url: string };

type RecentMessage = { peer: string; text: string; at: number; dir: 'in' | 'out' };

const POLL_MS = 2500;

export function WeChatTab() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status | null>(null);
  const [qr, setQr] = useState<QrPayload | null>(null);
  const [qrState, setQrState] = useState('wait');
  const [recent, setRecent] = useState<RecentMessage[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);
  // Redirect host after "scaned_but_redirect"; the vendor moves the poll.
  const redirectRef = useRef('');

  const loadStatus = useCallback(async () => {
    try {
      const { data } = await api.get<Status>('/api/v1/wechat/status');
      setStatus(data);
      return data;
    } catch {
      setError(t('wechat.errors.status'));
      return null;
    }
  }, [t]);

  const loadRecent = useCallback(async () => {
    try {
      const { data } = await api.get<{ messages: RecentMessage[] }>(
        '/api/v1/wechat/recent?limit=10',
      );
      setRecent(data.messages ?? []);
    } catch {
      /* the debug view is optional */
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startQr = useCallback(async () => {
    setBusy(true);
    setError('');
    stopPolling();
    redirectRef.current = '';
    try {
      const { data } = await api.get<QrPayload>('/api/v1/wechat/qrcode');
      setQr(data);
      setQrState('wait');

      pollRef.current = window.setInterval(async () => {
        try {
          const params = new URLSearchParams({ qr_value: data.qr_value });
          if (redirectRef.current) params.set('base_url', redirectRef.current);
          const res = await api.get<{ status: string; redirect_base?: string; bound?: boolean }>(
            `/api/v1/wechat/qr-status?${params.toString()}`,
          );
          setQrState(res.data.status);
          if (res.data.redirect_base) redirectRef.current = res.data.redirect_base;
          if (res.data.bound || res.data.status === 'confirmed') {
            stopPolling();
            setQr(null);
            await loadStatus();
            await loadRecent();
          } else if (res.data.status === 'expired') {
            stopPolling();
          }
        } catch {
          /* a failed poll is not fatal: the next tick retries */
        }
      }, POLL_MS);
    } catch {
      setError(t('wechat.errors.qrcode'));
    } finally {
      setBusy(false);
    }
  }, [loadRecent, loadStatus, stopPolling, t]);

  useEffect(() => {
    void (async () => {
      setError('');
      const s = await loadStatus();
      if (s?.bound) await loadRecent();
    })();
    // A failed load is often just a stale session: the panel calls once on
    // mount, so a 401 there left the error on screen long after the token had
    // been refreshed. Re-read whenever the tab comes back to the foreground.
    const onVisible = () => {
      if (document.visibilityState === 'visible') void loadStatus();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      stopPolling();
    };
  }, [loadStatus, loadRecent, stopPolling]);

  const unbind = useCallback(async () => {
    setBusy(true);
    try {
      await api.post('/api/v1/wechat/unbind');
      setQr(null);
      setQrState('wait');
      await loadStatus();
    } catch {
      setError(t('wechat.errors.unbind'));
    } finally {
      setBusy(false);
    }
  }, [loadStatus, t]);

  const qrHint =
    qrState === 'scaned'
      ? t('wechat.scanned')
      : qrState === 'expired'
        ? t('wechat.expired')
        : t('wechat.scanHint');

  return (
    <div className="max-w-2xl">
      <h3 className="text-base font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
        {t('wechat.title')}
      </h3>
      <p className="text-sm mb-6" style={{ color: 'var(--color-text-secondary)' }}>
        {t('wechat.subtitle')}
      </p>

      {error && (
        <div className="flex items-center gap-3 mb-4">
          <p className="text-sm" style={{ color: 'var(--color-down)' }}>
            {error}
          </p>
          <button
            type="button"
            onClick={() => void loadStatus()}
            className="px-2.5 py-1 text-xs rounded-md clips-focus-ring flex-shrink-0"
            style={{ border: '1px solid var(--color-border-default)', color: 'var(--color-text-primary)' }}
          >
            {t('wechat.retry')}
          </button>
        </div>
      )}

      {!status?.enabled && (
        <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          {t('wechat.notEnabled')}
        </p>
      )}

      {status?.enabled && status.bound && (
        <div
          className="rounded-lg p-4 mb-6"
          style={{ background: 'var(--color-bg-card)', border: '1px solid var(--color-border-muted)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ background: 'var(--color-success)' }}
              aria-hidden
            />
            <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {t('wechat.bound')}
            </span>
          </div>
          <dl className="text-xs grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt style={{ color: 'var(--color-text-tertiary)' }}>{t('wechat.account')}</dt>
            <dd style={{ color: 'var(--color-text-secondary)' }}>{status.account_id || '—'}</dd>
            <dt style={{ color: 'var(--color-text-tertiary)' }}>{t('wechat.mode')}</dt>
            <dd style={{ color: 'var(--color-text-secondary)' }}>{status.agent_mode || '—'}</dd>
            <dt style={{ color: 'var(--color-text-tertiary)' }}>{t('wechat.peers')}</dt>
            <dd style={{ color: 'var(--color-text-secondary)' }}>{status.peers ?? 0}</dd>
          </dl>
          <button
            type="button"
            onClick={unbind}
            disabled={busy}
            className="mt-4 px-3 py-1.5 text-sm rounded-md clips-focus-ring"
            style={{
              border: '1px solid var(--color-border-default)',
              color: 'var(--color-text-primary)',
              background: 'transparent',
            }}
          >
            {t('wechat.unbind')}
          </button>

          {recent.length > 0 && (
            <div className="mt-5">
              <p className="text-xs mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                {t('wechat.recent')}
              </p>
              <ul className="space-y-1">
                {recent.map((m, i) => (
                  <li
                    key={`${m.at}-${i}`}
                    className="text-xs truncate"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    <span style={{ color: 'var(--color-text-tertiary)' }}>
                      {m.dir === 'in' ? '←' : '→'}
                    </span>{' '}
                    {m.text}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {status?.enabled && !status.bound && (
        <div
          className="rounded-lg p-5 flex flex-col items-center"
          style={{ background: 'var(--color-bg-card)', border: '1px solid var(--color-border-muted)' }}
        >
          {qr ? (
            <>
              <div className="p-3 rounded-md" style={{ background: '#fff' }}>
                <QRCodeSVG value={qr.image_url} size={200} level="M" />
              </div>
              <p className="text-sm mt-4" style={{ color: 'var(--color-text-secondary)' }}>
                {qrHint}
              </p>
              <a
                href={qr.image_url}
                target="_blank"
                rel="noreferrer"
                className="text-xs mt-1 break-all text-center"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                {qr.image_url}
              </a>
              <div className="flex gap-2 mt-4">
                <button
                  type="button"
                  onClick={startQr}
                  disabled={busy}
                  className="px-3 py-1.5 text-sm rounded-md clips-focus-ring"
                  style={{ border: '1px solid var(--color-border-default)', color: 'var(--color-text-primary)' }}
                >
                  {t('wechat.refresh')}
                </button>
              </div>
            </>
          ) : (
            <button
              type="button"
              onClick={startQr}
              disabled={busy}
              className="px-4 py-2 text-sm rounded-md clips-focus-ring font-medium"
              style={{
                background: 'var(--color-btn-primary-bg)',
                color: 'var(--color-btn-primary-text)',
              }}
            >
              {busy ? t('wechat.loading') : t('wechat.showQr')}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
