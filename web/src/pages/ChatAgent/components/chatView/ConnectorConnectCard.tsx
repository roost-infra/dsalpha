/**
 * A small in-chat card for a bot that is allowed to use an app but has not
 * connected an account yet. It is the dsalpha form of OpenMausBot's connector
 * card: the bot does not fail silently on the first tool call that needs auth;
 * the user sees the missing connection beside the composer and can go connect.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { ArrowRight, PlugZap } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useBot } from '@/hooks/useBots';
import { useConnectedApps } from '@/pages/Apps/hooks';
import { threadDetailQuery } from '../../utils/threadQueries';
import './ConnectorConnectCard.css';

export function ConnectorConnectCard({
  threadId,
}: {
  threadId: string | null | undefined;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const liveThreadId = threadId && threadId !== '__default__' ? threadId : null;
  const { data: thread } = useQuery({
    ...threadDetailQuery(liveThreadId ?? ''),
    enabled: !!liveThreadId,
  });
  const { data: bot } = useBot(thread?.bot_id ?? null);
  const { data: connected } = useConnectedApps();

  const grants = bot?.connector_tools ?? {};
  const granted = Object.keys(grants).filter((slug) => slug !== '__none__');
  const apps = connected?.apps ?? [];
  const missing = granted
    .map((slug) => apps.find((app) => app.slug === slug))
    .filter((app) => app && app.accounts.length === 0);

  if (missing.length === 0) return null;

  const names = missing.map((app) => app!.name).join(', ');
  return (
    <div className="connector-connect-card" role="status" data-testid="connector-connect-card">
      <span className="connector-connect-icon" aria-hidden="true">
        <PlugZap className="h-4 w-4" />
      </span>
      <span className="connector-connect-copy">
        <span className="connector-connect-title">
          {t('chat.connectorConnect.title', { name: names })}
        </span>
        <span className="connector-connect-body">{t('chat.connectorConnect.body')}</span>
      </span>
      <Button size="sm" variant="outline" onClick={() => navigate('/apps')}>
        {t('chat.connectorConnect.action')}
        <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
