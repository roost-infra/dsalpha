import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AppWindow,
  Check,
  ExternalLink,
  Link2Off,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ErrorBanner } from '@/components/ui/error-banner';
import { ListSkeleton } from '@/components/mcp/McpPrimitives';
import { useToast } from '@/components/ui/use-toast';
import { failureText } from '@/lib/failureText';
import { useConnectedApps, useConnectConnectedApp, useDisconnectConnectedAccount, useSaveComposioKey } from './hooks';
import type { ConnectedApp, ConnectedAppsStatus } from './api';
import './Apps.css';

const COMPOSIO_KEYS_URL = 'https://app.composio.dev';

/** One app card: what it is, which accounts are connected, and the one action. */
function AppCard({
  app,
  onConnect,
  onDisconnect,
  busy,
}: {
  app: ConnectedApp;
  onConnect: () => void;
  onDisconnect: (id: string) => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  return (
    <article className="apps-card" data-testid={`app-card-${app.slug}`}>
      <header className="apps-card-head">
        <span className="apps-logo" aria-hidden="true">
          {app.logo ? (
            <img
              src={app.logo}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              onError={(event) => {
                event.currentTarget.style.display = 'none';
              }}
            />
          ) : (
            <AppWindow className="h-5 w-5" />
          )}
        </span>
        <div className="apps-card-title">
          <h3>{app.name}</h3>
          {app.connected && (
            <span className="apps-connected">
              <Check aria-hidden="true" className="h-3 w-3" />
              {t('apps.connected')}
            </span>
          )}
        </div>
      </header>

      {app.description && <p className="apps-card-desc">{app.description}</p>}

      {app.accounts.length > 0 && (
        <ul className="apps-accounts">
          {app.accounts.map((account) => (
            <li key={account.id} className="apps-account">
              <span className="apps-account-name">
                {account.alias || t('apps.defaultAccount')}
                <span className={`apps-account-status is-${account.status.toLowerCase()}`}>
                  {account.status.toLowerCase()}
                </span>
              </span>
              <button
                type="button"
                className="apps-account-remove"
                onClick={() => onDisconnect(account.id)}
                aria-label={t('apps.disconnectAccount', { name: account.alias || app.name })}
              >
                <Link2Off aria-hidden="true" className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <Button size="sm" variant={app.connected ? 'outline' : 'default'} onClick={onConnect} disabled={busy}>
        {app.connected ? (
          <>
            <Plus aria-hidden="true" className="h-3.5 w-3.5" />
            {t('apps.addAccount')}
          </>
        ) : (
          t('apps.connect')
        )}
      </Button>
    </article>
  );
}

/**
 * /apps — connect external accounts (GitHub, Gmail, Slack, …) to the bots.
 *
 * The page is a thin client of the account's Composio session: setup asks for
 * the project key once (or uses the deployment's), Connect opens the provider's
 * OAuth page, and Connected lists the accounts whose tokens stay with Composio.
 * There is no per-bot grant UI yet; every bot reaches the connector's tools.
 */
function Apps() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const query = useConnectedApps();
  const saveKey = useSaveComposioKey();
  const connect = useConnectConnectedApp();
  const disconnect = useDisconnectConnectedAccount();
  const [queryText, setQueryText] = useState('');
  const [key, setKey] = useState('');
  const [editingKey, setEditingKey] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const status: ConnectedAppsStatus | undefined = query.data;
  const configured = status?.configured === true;
  const apps = useMemo(() => status?.apps ?? [], [status?.apps]);
  const filtered = useMemo(() => {
    const needle = queryText.trim().toLowerCase();
    if (!needle) return apps;
    return apps.filter((app) =>
      `${app.name} ${app.slug} ${app.description}`.toLowerCase().includes(needle),
    );
  }, [apps, queryText]);
  const connectedCount = apps.filter((app) => app.connected).length;

  const save = async () => {
    const value = key.trim();
    if (!value) return;
    setFailure(null);
    try {
      await saveKey.mutateAsync(value);
      setKey('');
      setEditingKey(false);
      toast({ title: t('apps.keySavedTitle'), description: t('apps.keySavedNote') });
    } catch (error) {
      setFailure(failureText(error, t('apps.keyFailed')));
    }
  };

  const openConnect = (app: ConnectedApp) => {
    setFailure(null);
    connect.mutate(
      { slug: app.slug },
      {
        onSuccess: ({ url }) => {
          const opened = window.open(url, '_blank', 'noopener,noreferrer');
          if (!opened) {
            toast({ title: t('apps.popupTitle'), description: t('apps.popupNote') });
          }
          toast({
            title: t('apps.authorizeTitle', { name: app.name }),
            description: t('apps.authorizeNote'),
          });
          window.setTimeout(() => void query.refetch(), 2000);
        },
        onError: (error) => setFailure(failureText(error, t('apps.connectFailed'))),
      },
    );
  };

  const removeAccount = (id: string) => {
    setFailure(null);
    disconnect.mutate(id, {
      onError: (error) => setFailure(failureText(error, t('apps.removeFailed'))),
    });
  };

  const showSetup = !configured || editingKey;
  const busy = saveKey.isPending || connect.isPending || disconnect.isPending;

  return (
    <div className="apps-page">
      <div className="chrome-drag-strip" aria-hidden="true" />
      <div className="apps-scroll">
        <div className="apps-container">
          <header className="apps-header">
            <h1 className="apps-title">{t('apps.title')}</h1>
            <p className="apps-tagline">{t('apps.tagline')}</p>
            {configured && status?.using_deployment_key && (
              <span className="apps-deployment">
                <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />
                {t('apps.usingDeploymentKey')}
              </span>
            )}
          </header>

          {showSetup && (
            <section className="apps-setup" aria-labelledby="apps-setup-title">
              <h2 id="apps-setup-title" className="apps-setup-title">
                {t('apps.setupTitle')}
              </h2>
              <p className="apps-setup-copy">{t('apps.setupDescription')}</p>
              <label className="apps-key-field">
                <span>{t('apps.keyLabel')}</span>
                <Input
                  type="password"
                  value={key}
                  onChange={(event) => setKey(event.target.value)}
                  placeholder={t('apps.keyPlaceholder')}
                  autoComplete="off"
                  disabled={busy}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void save();
                  }}
                />
              </label>
              <p className="apps-key-hint">{t('apps.keyHint')}</p>
              <div className="apps-setup-actions">
                <Button onClick={() => void save()} disabled={busy || !key.trim()}>
                  {busy ? t('apps.saving') : t('apps.saveKey')}
                </Button>
                <a
                  className="apps-link"
                  href={COMPOSIO_KEYS_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
                  {t('apps.keyPortal')}
                </a>
                {configured && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setEditingKey(false);
                      setKey('');
                      setFailure(null);
                    }}
                  >
                    {t('apps.cancel')}
                  </Button>
                )}
              </div>
            </section>
          )}

          {failure && <ErrorBanner error={failure} />}
          {query.isError && (
            <ErrorBanner error={failureText(query.error, t('apps.loadFailed'))} />
          )}

          {configured && !showSetup && (
            <>
              <div className="apps-toolbar">
                <label className="apps-search">
                  <Search aria-hidden="true" className="h-4 w-4" />
                  <input
                    value={queryText}
                    onChange={(event) => setQueryText(event.target.value)}
                    placeholder={t('apps.searchPlaceholder')}
                    aria-label={t('apps.searchLabel')}
                  />
                </label>
                <span className="apps-count">
                  {t('apps.connectedCount', { count: connectedCount })}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setEditingKey(true);
                    setFailure(null);
                  }}
                  disabled={busy}
                >
                  {t('apps.changeKey')}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void query.refetch()}
                  disabled={query.isFetching}
                  aria-label={t('apps.refresh')}
                >
                  <RefreshCw aria-hidden="true" className="h-4 w-4" />
                  {t('apps.refresh')}
                </Button>
              </div>

              {query.isLoading && <ListSkeleton rows={4} />}

              {!query.isLoading && filtered.length === 0 && (
                <p className="apps-empty">{t('apps.noMatches')}</p>
              )}

              {!query.isLoading && filtered.length > 0 && (
                <div className="apps-grid">
                  {filtered.map((app) => (
                    <AppCard
                      key={app.slug}
                      app={app}
                      onConnect={() => openConnect(app)}
                      onDisconnect={removeAccount}
                      busy={busy}
                    />
                  ))}
                </div>
              )}
            </>
          )}

          <p className="apps-footnote">{t('apps.footnote')}</p>
        </div>
      </div>
    </div>
  );
}

export default Apps;
