import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Copy } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { formatApiErrorDetail } from '@/api/errors';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Loader } from '@/components/ui/loader';
import { copyText } from '@/lib/clipboard';
import type { Computer } from '@/types/api';

import { getSshCommand } from './desktopApi';

export function ComputerSshDialog({ computer, onClose }: { computer: Computer; onClose: () => void }) {
  const { t } = useTranslation();
  const [copyStatus, setCopyStatus] = useState<'done' | 'failed' | null>(null);
  const request = useMutation({ mutationFn: () => getSshCommand(computer.computer_id), gcTime: 0 });
  const { data } = request;

  async function copyCommand(command: string) {
    try {
      await copyText(command);
      setCopyStatus('done');
    } catch {
      setCopyStatus('failed');
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('computer.cloud.sshTitle', { name: computer.name })}</DialogTitle>
          <DialogDescription>{t('computer.cloud.sshDescription')}</DialogDescription>
        </DialogHeader>
        {data ? (
          <div className="grid gap-3">
            <pre className="overflow-auto rounded-md border bg-input p-3 text-sm"><code>{data.command}</code></pre>
            {data.expires_in_minutes !== null && (
              <p className="text-sm text-muted-foreground">{t('computer.cloud.sshExpires', { minutes: data.expires_in_minutes })}</p>
            )}
            <Button variant="outline" className="justify-self-start" onClick={() => void copyCommand(data.command)}>
              <Copy aria-hidden="true" /> {t('computer.cloud.copyCommand')}
            </Button>
            {copyStatus && (
              <p role="status" className="text-sm">{t(copyStatus === 'done' ? 'computer.cloud.copied' : 'computer.cloud.copyFailed')}</p>
            )}
          </div>
        ) : (
          <div className="grid gap-3">
            {request.error && <p role="alert" className="text-sm text-destructive">{formatApiErrorDetail(request.error)}</p>}
            <Button className="justify-self-start" onClick={() => request.mutate()} disabled={request.isPending}>
              {request.isPending && <Loader size={14} />}
              {t('computer.cloud.generateSsh')}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
