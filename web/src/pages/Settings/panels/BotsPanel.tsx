import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { BotMessageSquare, Pause, Pencil, Play, Plus, Trash2 } from 'lucide-react';
import type { BotApproval, BotCreateInput, BotInfo, BotUpdateInput } from '@/api/bots';
import { ApiError } from '@/api/client';
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
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/use-toast';
import { useAllWorkspaces } from '@/hooks/useAllWorkspaces';
import { useBots, useCreateBot, useDeleteBot, useUpdateBot } from '@/hooks/useBots';
import type { Workspace } from '@/types/api';
import { SettingsCardBody, SettingsGroup, SettingRow } from '../components/SettingsLayout';
import { SETTINGS } from '../sections';

/** The approval levels, least autonomous first; the labels are catalog keys. */
const APPROVALS: readonly BotApproval[] = ['ask', 'edits', 'auto', 'full'];

const APPROVAL_KEY: Record<BotApproval, string> = {
  ask: 'bots.approval.ask',
  edits: 'bots.approval.edits',
  auto: 'bots.approval.auto',
  full: 'bots.approval.full',
};

/** A persona may run to 20k characters; the row shows its opening line only. */
function personaPreview(persona: string): string {
  const line = persona.trim().split('\n')[0].trim();
  return line.length > 140 ? `${line.slice(0, 139)}…` : line;
}

/** The server writes refusals meant for the user; anything else gets ours. */
function failureText(error: unknown, fallback: string): string | null {
  if (!error) return null;
  return error instanceof ApiError && error.message ? error.message : fallback;
}

function FormField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
        {label}
      </span>
      {children}
    </label>
  );
}

interface BotRowProps {
  bot: BotInfo;
  busy: boolean;
  onEdit: (bot: BotInfo) => void;
  onDelete: (bot: BotInfo) => void;
  onToggleStatus: (bot: BotInfo) => void;
}

function BotRow({ bot, busy, onEdit, onDelete, onToggleStatus }: BotRowProps) {
  const { t } = useTranslation();
  const isChief = bot.role === 'chief_of_staff';
  const persona = personaPreview(bot.persona);

  return (
    <SettingRow
      label={
        <span className="flex flex-wrap items-center gap-2">
          <span>{bot.name}</span>
          {isChief ? (
            <Badge variant="info">{t('bots.readOnly')}</Badge>
          ) : (
            <Badge variant="muted">{t('agents.analyst')}</Badge>
          )}
          {bot.status === 'paused' && <Badge variant="warning">{t('bots.pausedBadge')}</Badge>}
        </span>
      }
      description={
        isChief ? (
          t('bots.chiefOfStaffDesc')
        ) : (
          <>
            {persona && <span>{persona} · </span>}
            {t('bots.summaryLine', {
              model: bot.model ?? t('bots.modelFollowsThread'),
              approval: t(APPROVAL_KEY[bot.approval]),
            })}
          </>
        )
      }
    >
      {/* The Chief of Staff is derived from Home: nothing here may edit or
          delete it, and the server refuses a delete of its own. */}
      {!isChief && (
        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            disabled={busy}
            aria-label={
              bot.status === 'paused'
                ? t('bots.resumeNamed', { name: bot.name })
                : t('bots.pauseNamed', { name: bot.name })
            }
            onClick={() => onToggleStatus(bot)}
          >
            {bot.status === 'paused' ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            disabled={busy}
            aria-label={t('bots.editNamed', { name: bot.name })}
            onClick={() => onEdit(bot)}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            disabled={busy}
            aria-label={t('bots.deleteNamed', { name: bot.name })}
            onClick={() => onDelete(bot)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      )}
    </SettingRow>
  );
}

interface BotEditorProps {
  /** The bot being edited, or null to create one. */
  bot: BotInfo | null;
  /** The workspaces a bot can be created in: Home holds the Chief of Staff. */
  workspaces: readonly Workspace[];
  maxBots: number;
  /** The workspace a per-workspace "add" had in hand. */
  initialWorkspaceId?: string;
  onClose: () => void;
}

/** Create or edit one bot. Mounted only while open, so the drafts reset. */
function BotEditor({ bot, workspaces, maxBots, initialWorkspaceId, onClose }: BotEditorProps) {
  const { t } = useTranslation();
  const createBot = useCreateBot();
  const updateBot = useUpdateBot();
  const editing = bot !== null;
  const [name, setName] = useState(bot?.name ?? '');
  const [workspaceId, setWorkspaceId] = useState(
    initialWorkspaceId && workspaces.some((ws) => ws.workspace_id === initialWorkspaceId)
      ? initialWorkspaceId
      : (bot?.workspace_id ?? workspaces[0]?.workspace_id ?? ''),
  );
  const [persona, setPersona] = useState(bot?.persona ?? '');
  const [provider, setProvider] = useState(bot?.provider ?? '');
  const [model, setModel] = useState(bot?.model ?? '');
  const [approval, setApproval] = useState<BotApproval>(bot?.approval ?? 'ask');
  const busy = createBot.isPending || updateBot.isPending;
  const trimmedName = name.trim();
  const canSubmit = !!trimmedName && (editing || !!workspaceId) && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    try {
      if (bot) {
        const patch: BotUpdateInput = {
          name: trimmedName,
          persona: persona.trim(),
          model: model.trim() || null,
          approval,
        };
        await updateBot.mutateAsync({ botId: bot.bot_id, patch });
      } else {
        const input: BotCreateInput = {
          workspace_id: workspaceId,
          name: trimmedName,
          role: 'analyst',
          persona: persona.trim(),
          provider: provider.trim() || null,
          model: model.trim() || null,
          approval,
        };
        await createBot.mutateAsync(input);
      }
      onClose();
    } catch {
      // The refusal is drawn under the fields; a rejected request is not a
      // reason to throw away what the user typed.
    }
  };

  const failure = failureText(createBot.error ?? updateBot.error, t('bots.failed'));

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
      <DialogContent style={{ backgroundColor: 'var(--color-bg-page)', borderColor: 'var(--color-border-muted)' }}>
        <DialogHeader>
          <DialogTitle>{bot ? t('bots.editTitle', { name: bot.name }) : t('bots.createTitle')}</DialogTitle>
          <DialogDescription>
            {editing ? t('bots.editDescription') : t('bots.createDescription', { max: maxBots })}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <FormField label={t('bots.name')}>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('bots.namePlaceholder')}
              maxLength={64}
              autoFocus
            />
          </FormField>

          {!editing && (
            <FormField label={t('bots.workspace')}>
              <Select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
                {workspaces.map((workspace) => (
                  <option key={workspace.workspace_id} value={workspace.workspace_id}>
                    {workspace.name}
                  </option>
                ))}
              </Select>
            </FormField>
          )}
          {!editing && workspaces.length === 0 && (
            <p className="text-xs" style={{ color: 'var(--color-loss)' }}>{t('bots.noWorkspace')}</p>
          )}

          <FormField label={t('bots.persona')}>
            <Textarea
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              placeholder={t('bots.personaPlaceholder')}
              rows={3}
            />
          </FormField>

          <FormField label={t('bots.approvalLabel')}>
            <Select value={approval} onChange={(e) => setApproval(e.target.value as BotApproval)}>
              {APPROVALS.map((level) => (
                <option key={level} value={level}>{t(APPROVAL_KEY[level])}</option>
              ))}
            </Select>
          </FormField>

          <FormField label={t('bots.model')}>
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={t('bots.modelPlaceholder')}
            />
          </FormField>

          {/* Only a create sends the provider: an edit changes what the row
              already answers with, not where it comes from. */}
          {!editing && (
            <FormField label={t('bots.provider')}>
              <Input
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                placeholder={t('bots.providerPlaceholder')}
              />
            </FormField>
          )}
        </div>

        {failure && <ErrorBanner error={failure} />}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <Button onClick={() => { void submit(); }} disabled={!canSubmit}>
            {busy ? t('common.saving') : editing ? t('common.save') : t('common.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** A bot is soft-deleted; its threads stay readable. The Chief of Staff never
 *  reaches this dialog, and the server refuses a delete of its own. */
function BotDeleteDialog({ bot, onClose }: { bot: BotInfo; onClose: () => void }) {
  const { t } = useTranslation();
  const { mutate, isPending, error } = useDeleteBot();
  const failure = failureText(error, t('bots.failed'));

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !isPending) onClose(); }}>
      <DialogContent style={{ backgroundColor: 'var(--color-bg-page)', borderColor: 'var(--color-border-muted)' }}>
        <DialogHeader>
          <DialogTitle>{t('bots.deleteTitle')}</DialogTitle>
          <DialogDescription>{t('bots.deleteDescription', { name: bot.name })}</DialogDescription>
        </DialogHeader>
        {failure && <ErrorBanner error={failure} />}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>{t('common.cancel')}</Button>
          <Button
            variant="destructive"
            onClick={() => mutate(bot.bot_id, { onSuccess: onClose })}
            disabled={isPending}
          >
            {isPending ? t('common.saving') : t('bots.deleteConfirmAction')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Bots: the identities a workspace answers as. One list answer carries every
 * workspace's bots, so the section groups it by workspace; the derived Chief
 * of Staff is drawn read-only. Writes go through the shared hooks, which land
 * each answer in the list and in the single-row cache.
 */
export function BotsPanel() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { data, isLoading, isError, error, refetch } = useBots();
  const { data: workspacesData, isLoading: areWorkspacesLoading } = useAllWorkspaces({ includeHome: true });
  const { mutate: updateBot, isPending: isUpdating } = useUpdateBot();
  const [editor, setEditor] = useState<{ bot: BotInfo | null; workspaceId?: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BotInfo | null>(null);

  const workspaces = workspacesData?.workspaces ?? [];
  const bots = data?.bots ?? [];
  const maxBots = data?.max_bots ?? 20;
  // Home holds the derived Chief of Staff, so the server refuses a bot made
  // there; every other workspace takes one.
  const placeable = workspaces.filter((workspace) => !workspace.is_home);
  const groups = workspaces.flatMap((workspace) => {
    const rows = bots.filter((bot) => bot.workspace_id === workspace.workspace_id);
    return rows.length > 0 ? [{ workspace, bots: rows }] : [];
  });
  const loading = isLoading || areWorkspacesLoading;
  const noWorkspace = placeable.length === 0;

  const toggleStatus = (bot: BotInfo) => {
    updateBot(
      { botId: bot.bot_id, patch: { status: bot.status === 'paused' ? 'active' : 'paused' } },
      {
        onError: () => {
          toast({ variant: 'destructive', title: t('common.error'), description: t('bots.failed') });
        },
      },
    );
  };

  return (
    <>
      {loading && (
        <SettingsGroup title={t('bots.title')}>
          <SettingsCardBody>
            <span role="status">{t('common.loading')}</span>
          </SettingsCardBody>
        </SettingsGroup>
      )}

      {!loading && isError && groups.length === 0 && (
        <SettingsGroup title={t('bots.title')}>
          <SettingsCardBody>
            <ErrorBanner error={failureText(error, t('bots.failed'))} />
            <div className="mt-3">
              <Button variant="ghost" size="sm" onClick={() => { void refetch(); }}>{t('common.retry')}</Button>
            </div>
          </SettingsCardBody>
        </SettingsGroup>
      )}

      {!loading && !isError && groups.length === 0 && (
        <SettingsGroup
          title={t('bots.title')}
          action={
            <Button variant="outline" size="sm" disabled={noWorkspace} onClick={() => setEditor({ bot: null })}>
              <Plus className="mr-1.5 h-4 w-4" />
              {t('bots.create')}
            </Button>
          }
        >
          <SettingsCardBody id={SETTINGS.bots.anchor} className="py-8 text-center">
            <BotMessageSquare
              aria-hidden
              className="mx-auto h-8 w-8"
              style={{ color: 'var(--color-text-tertiary)' }}
            />
            <p className="mt-2 text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {t('bots.emptyTitle')}
            </p>
            <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {t('bots.emptyDescription')}
            </p>
            {noWorkspace && (
              <p className="mt-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                {t('bots.noWorkspace')}
              </p>
            )}
          </SettingsCardBody>
        </SettingsGroup>
      )}

      {!loading && !isError && groups.length > 0 && (
        <SettingsGroup
          title={t('bots.title')}
          description={t('bots.description')}
          action={
            <Button variant="outline" size="sm" disabled={noWorkspace} onClick={() => setEditor({ bot: null })}>
              <Plus className="mr-1.5 h-4 w-4" />
              {t('bots.create')}
            </Button>
          }
        >
          <SettingsCardBody id={SETTINGS.bots.anchor}>
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {t('bots.summary', { bots: bots.length, workspaces: groups.length })}
            </p>
          </SettingsCardBody>
        </SettingsGroup>
      )}

      {!loading && groups.map(({ workspace, bots: rows }) => (
        <SettingsGroup
          key={workspace.workspace_id}
          title={workspace.name}
          description={t('bots.groupCount', { n: rows.length })}
          action={
            workspace.is_home ? undefined : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setEditor({ bot: null, workspaceId: workspace.workspace_id })}
              >
                <Plus className="mr-1.5 h-4 w-4" />
                {t('bots.addToWorkspace')}
              </Button>
            )
          }
        >
          {rows.map((bot) => (
            <BotRow
              key={bot.bot_id}
              bot={bot}
              busy={isUpdating}
              onEdit={(target) => setEditor({ bot: target })}
              onDelete={(target) => setDeleteTarget(target)}
              onToggleStatus={toggleStatus}
            />
          ))}
        </SettingsGroup>
      ))}

      {editor && (
        <BotEditor
          bot={editor.bot}
          workspaces={placeable}
          maxBots={maxBots}
          initialWorkspaceId={editor.workspaceId}
          onClose={() => setEditor(null)}
        />
      )}
      {deleteTarget && (
        <BotDeleteDialog bot={deleteTarget} onClose={() => setDeleteTarget(null)} />
      )}
    </>
  );
}
