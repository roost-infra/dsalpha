import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ExternalLink } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/use-toast';
import { useImportMcpCatalogServers } from '@/hooks/useMcpServers';
import { formatApiErrorDetail } from '@/pages/ChatAgent/utils/api';
import { HITHINK_API_KEY_URL, HITHINK_SERVERS, buildHithinkPayload } from './hithinkPreset';

/**
 * One-click install of the Hithink (同花顺) connector preset.
 *
 * The key is typed here, posted once as the headers of eight remote servers,
 * and never shown again: the import path extracts each literal into the user's
 * vault and rewrites the header to a `${vault:...}` reference before saving.
 * The rows land switched off, like every imported connector, so the user
 * decides which of the eight data domains reaches the agent.
 */
export function HithinkPresetDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const importServers = useImportMcpCatalogServers();
  const [apiKey, setApiKey] = useState('');
  const [failure, setFailure] = useState<string | null>(null);

  const trimmed = apiKey.trim();
  const busy = importServers.isPending;

  const submit = async () => {
    if (!trimmed || busy) return;
    setFailure(null);
    try {
      const report = await importServers.mutateAsync(buildHithinkPayload(trimmed));
      const created = report.results.filter((row) => row.status === 'created').length;
      const failed = report.results.filter(
        (row) => row.status !== 'created' && row.status !== 'exists',
      ).length;
      if (failed > 0 && created === 0) {
        const first = report.results.find(
          (row) => row.status !== 'created' && row.status !== 'exists',
        );
        setFailure(first?.reason || first?.error || t('plugins.hithink.failed'));
        return;
      }
      setApiKey('');
      onClose();
      toast({
        title: t('plugins.hithink.addedTitle', { count: created }),
        description: t('plugins.hithink.addedNote'),
      });
      if (failed > 0) {
        toast({
          variant: 'destructive',
          title: t('plugins.hithink.partialTitle'),
          description: t('plugins.hithink.partialNote', { count: failed }),
        });
      }
    } catch (error) {
      setFailure(formatApiErrorDetail(error) || t('plugins.hithink.failed'));
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !busy) {
          setApiKey('');
          setFailure(null);
          onClose();
        }
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('plugins.hithink.title')}</DialogTitle>
          <DialogDescription>{t('plugins.hithink.description')}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium">{t('plugins.hithink.keyLabel')}</span>
            <Input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={t('plugins.hithink.keyPlaceholder')}
              autoComplete="off"
              autoFocus
              disabled={busy}
              aria-describedby="hithink-key-hint"
            />
            <span id="hithink-key-hint" className="text-xs text-muted-foreground">
              {t('plugins.hithink.keyHint')}
            </span>
          </label>

          <a
            className="inline-flex w-fit items-center gap-1 text-xs text-(--color-accent-primary) hover:underline"
            href={HITHINK_API_KEY_URL}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink aria-hidden="true" className="h-3 w-3" />
            {t('plugins.hithink.keyPortal')}
          </a>

          {failure && (
            <p role="alert" className="text-sm text-(--color-loss)">
              {failure}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void submit()} disabled={!trimmed || busy}>
            {busy
              ? t('plugins.hithink.adding')
              : t('plugins.hithink.add', { count: HITHINK_SERVERS.length })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
