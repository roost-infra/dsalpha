import { useQuery } from '@tanstack/react-query';
import { History } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Loader } from '@/components/ui/loader';
import { useLocale } from '@/hooks/useLocale';
import { formatTimestamp } from '@/lib/format';
import { queryKeys } from '@/lib/queryKeys';

import { getDesktopHistory, type DesktopSessionSummary } from './desktopApi';

function statusKey(session: DesktopSessionSummary) {
  if (!session.ended_at) return 'computer.cloud.historyActive';
  switch (session.end_reason) {
    case 'revoked': return 'computer.cloud.historyRevoked';
    case 'unavailable': return 'computer.cloud.historyUnavailable';
    case 'interrupted': return 'computer.cloud.historyInterrupted';
    default: return 'computer.cloud.historyEnded';
  }
}

function SessionList({ computerId }: { computerId: string }) {
  const { t } = useTranslation();
  const locale = useLocale();
  const history = useQuery({
    queryKey: queryKeys.computers.desktopHistory(computerId),
    queryFn: ({ signal }) => getDesktopHistory(computerId, signal),
    gcTime: 0,
    refetchInterval: 10_000,
    retry: false,
  });

  if (history.isPending) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader size={14} /> {t('computer.cloud.historyLoading')}
      </p>
    );
  }
  if (history.isError) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <p role="alert" className="text-sm text-destructive">{t('computer.cloud.historyFailed')}</p>
        <Button size="sm" variant="outline" disabled={history.isFetching} onClick={() => void history.refetch()}>
          {t('computer.cloud.retry')}
        </Button>
      </div>
    );
  }
  if (history.data.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('computer.cloud.historyEmpty')}</p>;
  }
  return (
    <ol className="max-h-[55dvh] min-h-0 divide-y overflow-y-auto">
      {history.data.map((session) => (
        <li key={session.session_id} className="space-y-1 py-3 text-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="font-medium">{t(session.role === 'control' ? 'computer.cloud.control' : 'computer.cloud.view')}</span>
            <span className="text-muted-foreground">{t(statusKey(session))}</span>
          </div>
          <p className="text-xs text-muted-foreground">
            {t('computer.cloud.historyStartedAt', { time: formatTimestamp(session.started_at, locale) })}
          </p>
          {session.ended_at && (
            <p className="text-xs text-muted-foreground">
              {t('computer.cloud.historyEndedAt', { time: formatTimestamp(session.ended_at, locale) })}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

export function DesktopHistory({ computerId }: { computerId: string }) {
  const { t } = useTranslation();
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="outline">
          <History aria-hidden="true" /> {t('computer.cloud.history')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('computer.cloud.history')}</DialogTitle>
          <DialogDescription>{t('computer.cloud.historyDescription')}</DialogDescription>
        </DialogHeader>
        <SessionList computerId={computerId} />
      </DialogContent>
    </Dialog>
  );
}
