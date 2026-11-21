import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/ui/error-banner';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { useToast } from '@/components/ui/use-toast';
import { useAllWorkspaces } from '@/hooks/useAllWorkspaces';
import { failureText } from '@/lib/failureText';
import { useInstallMarketBot } from '../hooks';
import type { InstallTarget } from './BotDetailDialog';

/**
 * Install a template into one of the caller's workspaces.
 *
 * The workspace list is the app's own workspace read (`useAllWorkspaces`), the
 * same one the Settings bot editor uses, with Home filtered out: Home holds
 * the derived Chief of Staff and the server refuses a new bot there. The name
 * starts as the template's own and stays editable, since a workspace at its
 * bot cap or a taken name is the server's 409 to explain.
 *
 * A refusal is drawn from the server's `detail` (400 Home, 404 unknown slug,
 * 409 name or cap), so the reader sees what actually refused rather than a
 * generic failure.
 */
export function InstallDialog({
  target,
  onClose,
  onInstalled,
}: {
  target: InstallTarget;
  onClose: () => void;
  onInstalled: () => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const install = useInstallMarketBot();
  const {
    data,
    isLoading,
    isError: workspacesFailed,
    error: workspacesError,
    refetch: refetchWorkspaces,
  } = useAllWorkspaces();
  const [name, setName] = useState(target.name);
  // Empty until the reader picks one; the first real workspace stands in until
  // then, so the form has a valid target as soon as the list lands.
  const [pickedWorkspaceId, setPickedWorkspaceId] = useState('');

  const workspaces = useMemo(
    () => (data?.workspaces ?? []).filter((workspace) => !workspace.is_home),
    [data],
  );
  const chosenWorkspaceId =
    pickedWorkspaceId || workspaces[0]?.workspace_id || '';
  const chosenWorkspace = workspaces.find(
    (workspace) => workspace.workspace_id === chosenWorkspaceId,
  );
  const trimmedName = name.trim();
  const busy = install.isPending;
  const canSubmit = !!chosenWorkspaceId && !!trimmedName && !busy;
  const failure = failureText(install.error, t('store.installFailed'));
  const workspacesFailure = failureText(
    workspacesFailed ? workspacesError : null,
    t('store.workspacesLoadFailed'),
  );

  const submit = async () => {
    if (!canSubmit) return;
    try {
      const result = await install.mutateAsync({
        slug: target.slug,
        input: { workspace_id: chosenWorkspaceId, name: trimmedName },
      });
      toast({
        title: t('store.installSuccessTitle'),
        description: t('store.installSuccess', {
          name: result.bot.name,
          workspace: chosenWorkspace?.name ?? '',
        }),
      });
      onInstalled();
    } catch {
      // The refusal stays on screen under the fields; the typed name and the
      // chosen workspace are kept so a rename is the only correction needed.
    }
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
      <DialogContent
        className="store-dialog store-install-dialog"
        style={{ backgroundColor: 'var(--color-bg-page)', borderColor: 'var(--color-border-muted)' }}
      >
        <DialogHeader>
          <DialogTitle>{t('store.installTitle', { name: target.name })}</DialogTitle>
          <DialogDescription>{t('store.installDescription')}</DialogDescription>
        </DialogHeader>

        {isLoading && (
          <p className="store-detail-muted" role="status">{t('store.workspacesLoading')}</p>
        )}

        {!isLoading && workspacesFailed && (
          <div className="flex flex-col items-start gap-2">
            <ErrorBanner error={workspacesFailure} />
            <Button variant="ghost" size="sm" onClick={() => void refetchWorkspaces()}>
              {t('common.retry')}
            </Button>
          </div>
        )}

        {!isLoading && !workspacesFailed && workspaces.length === 0 && (
          <p className="store-detail-muted">{t('store.noWorkspace')}</p>
        )}

        {!isLoading && !workspacesFailed && workspaces.length > 0 && (
          <div className="store-install-fields">
            <label className="store-field">
              <span className="store-field-label">{t('store.installWorkspace')}</span>
              <Select
                aria-label={t('store.installWorkspace')}
                value={chosenWorkspaceId}
                onChange={(event) => setPickedWorkspaceId(event.target.value)}
                disabled={busy}
              >
                {workspaces.map((workspace) => (
                  <option key={workspace.workspace_id} value={workspace.workspace_id}>
                    {workspace.name}
                  </option>
                ))}
              </Select>
            </label>

            <label className="store-field">
              <span className="store-field-label">{t('store.installName')}</span>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t('store.installNamePlaceholder')}
                maxLength={64}
                autoFocus
                disabled={busy}
              />
            </label>
          </div>
        )}

        {failure && !isLoading && !workspacesFailed && <ErrorBanner error={failure} />}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => { void submit(); }} disabled={!canSubmit || workspacesFailed}>
            {busy ? t('store.installing') : t('store.install')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
