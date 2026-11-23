import { lazy, Suspense, useRef, useState } from 'react';
import { ArrowLeft, FolderOpen, Maximize2, Monitor, Plus, Terminal } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';

import { formatApiErrorDetail } from '@/api/errors';
import { Button } from '@/components/ui/button';
import { buttonClass } from '@/components/ui/button-class';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Loader } from '@/components/ui/loader';
import { useAllWorkspaces } from '@/hooks/useAllWorkspaces';
import { useLocale } from '@/hooks/useLocale';
import { useNow } from '@/hooks/useNow';
import { useWorkspaceLabel } from '@/hooks/useWorkspaceLabel';
import { formatClock } from '@/lib/elapsed';
import { createFormatter, formatTimestamp } from '@/lib/format';
import { cn } from '@/lib/utils';
import { PowerButton } from '@/pages/ChatAgent/components/computerParts';
import { ComputerStatusIndicator } from '@/pages/ChatAgent/components/computerStatusUi';
import { computerSourceLabel } from '@/pages/ChatAgent/components/providerUi';
import { normalizeTier, tierLabel } from '@/pages/ChatAgent/components/tierUi';
import { openComputersPanel, useComputersPanel } from '@/pages/ChatAgent/hooks/computerPanelStore';
import { useComputerActions } from '@/pages/ChatAgent/hooks/useComputerActions';
import { useComputers, useComputerProviders, useComputerStatusFanout } from '@/pages/ChatAgent/hooks/useComputers';
import { desktopPath, PLATFORM_NAMES, workspaceFilesPath } from '@/pages/ChatAgent/utils/computerPlatform';
import { isComputerPreparing, liveComputers } from '@/pages/ChatAgent/utils/computerStatus';
import type { Computer, ComputerProviderOption, Workspace } from '@/types/api';

import { ComputerSshDialog } from './ComputerSshDialog';
import { DesktopPreview } from './DesktopPreview';
import { useDesktopSession } from './useDesktopSession';

const ComputersDialogHost = lazy(() => import('@/pages/ChatAgent/components/ComputersDialogHost'));

const formatCredits = createFormatter({ maximumFractionDigits: 0 });
const actionLink = buttonClass({ size: 'sm', variant: 'outline' });
type PowerMutation = ReturnType<typeof useComputerActions>['power'];

function ComputerPower({ computer, power, sleep }: { computer: Computer; power: PowerMutation; sleep?: boolean }) {
  return (
    <PowerButton
      computer={computer}
      sleep={sleep}
      actions={{
        powerBusy: power.isPending && power.variables.computerId === computer.computer_id,
        power: (action) => power.mutate({ computerId: computer.computer_id, action }),
      }}
    />
  );
}

function WorkspaceFiles({ workspaces, selectedId }: { workspaces: Workspace[]; selectedId?: string | null }) {
  const { t } = useTranslation();
  const workspaceLabel = useWorkspaceLabel();
  if (workspaces.length === 0) return null;
  const target = workspaces.find((workspace) => workspace.workspace_id === selectedId)
    ?? (workspaces.length === 1 ? workspaces[0] : null);
  const label = <><FolderOpen aria-hidden="true" /> {t('computer.cloud.files')}</>;
  if (target) {
    return <Link className={actionLink} to={workspaceFilesPath(target.workspace_id)}>{label}</Link>;
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button size="sm" variant="outline">{label}</Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-72 overflow-y-auto">
        {workspaces.map((workspace) => (
          <DropdownMenuItem key={workspace.workspace_id} asChild>
            <Link to={workspaceFilesPath(workspace.workspace_id)}>{workspaceLabel(workspace)}</Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ComputerTile({ computer, provider, workspaces, now, power, onSsh }: {
  computer: Computer;
  provider: ComputerProviderOption | undefined;
  workspaces: Workspace[];
  now: number;
  power: PowerMutation;
  onSsh: () => void;
}) {
  const { t } = useTranslation();
  const locale = useLocale();
  const running = computer.status === 'running';
  const startedAt = computer.running_since ? Date.parse(computer.running_since) : null;
  const os = computer.os_platform ? PLATFORM_NAMES[computer.os_platform] : computer.kind === 'ssh' ? null : PLATFORM_NAMES.linux;
  const sshAvailable = (computer.supports_ssh ?? provider?.supports_ssh) && !(computer.kind === 'ssh' && computer.ssh?.tunnel);
  return (
    <article aria-label={computer.name} className="grid content-start gap-4 rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="truncate font-semibold" title={computer.name}>{computer.name}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{computerSourceLabel(t, computer, false)}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 text-xs text-muted-foreground">
          {os && <span className="rounded-full border px-2 py-0.5">{os}</span>}
          <ComputerStatusIndicator status={computer.status} preparing={isComputerPreparing(computer)} />
        </div>
      </div>
      <DesktopPreview computer={computer} />
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        {computer.kind !== 'ssh' && (
          <div><dt className="text-xs text-muted-foreground">{t('computer.cloud.spec')}</dt><dd>{tierLabel(t, normalizeTier(computer.resource_tier))}</dd></div>
        )}
        {computer.region && <div><dt className="text-xs text-muted-foreground">{t('computer.cloud.region')}</dt><dd>{computer.region}</dd></div>}
        {startedAt !== null && Number.isFinite(startedAt) && (
          <div><dt className="text-xs text-muted-foreground">{t('computer.cloud.uptime')}</dt><dd className="tabular-nums">{formatClock(now - startedAt)}</dd></div>
        )}
        {computer.estimated_credits != null && (
          <div><dt className="text-xs text-muted-foreground">{t('computer.cloud.estimatedCost')}</dt><dd className="tabular-nums">{t('computer.cloud.credits', { value: formatCredits(computer.estimated_credits, locale) })}</dd></div>
        )}
        {computer.reservation_expires_at && (
          <div><dt className="text-xs text-muted-foreground">{t('computer.cloud.reservationExpires')}</dt><dd>{formatTimestamp(computer.reservation_expires_at, locale)}</dd></div>
        )}
      </dl>
      <div className="flex flex-wrap items-center gap-2">
        {computer.desktop_transport && (
          <Link className={actionLink} to={desktopPath(computer.computer_id)}>
            <Monitor aria-hidden="true" /> {t('computer.cloud.openDesktop')}
          </Link>
        )}
        <WorkspaceFiles workspaces={workspaces} />
        {sshAvailable && (
          <Button type="button" variant="outline" size="sm" onClick={onSsh} disabled={!running}>
            <Terminal aria-hidden="true" /> SSH
          </Button>
        )}
        <ComputerPower computer={computer} power={power} sleep={provider?.supports_sleep} />
        <Button size="sm" variant="ghost" onClick={() => openComputersPanel({ view: 'details', computerId: computer.computer_id })}>
          {t('computer.card.details', 'Details')}
        </Button>
      </div>
      {power.error && power.variables?.computerId === computer.computer_id && (
        <p role="alert" className="text-sm text-destructive">{formatApiErrorDetail(power.error)}</p>
      )}
    </article>
  );
}

function Desktop({ computer, workspaces, selectedId, power, sleep }: {
  computer: Computer;
  workspaces: Workspace[];
  selectedId: string | null;
  power: PowerMutation;
  sleep?: boolean;
}) {
  const { t } = useTranslation();
  const { state, vnc, picture, connect, disconnect } = useDesktopSession(computer.computer_id);
  const fullscreen = useRef<HTMLElement>(null);
  const [fullscreenError, setFullscreenError] = useState(false);
  const running = computer.status === 'running';
  const connecting = state.status === 'connecting' || state.status === 'reconnecting';
  const connected = state.status === 'connected';
  const active = connected || connecting;

  async function toggleFullscreen() {
    setFullscreenError(false);
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await fullscreen.current?.requestFullscreen();
    } catch {
      setFullscreenError(true);
    }
  }

  return (
    <section ref={fullscreen} className="flex min-h-full flex-col gap-4 bg-page p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <Link to="/computers" className="inline-flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-3.5" aria-hidden="true" /> {t('computer.computers')}
          </Link>
          <h1 className="title-font truncate text-2xl font-semibold">{computer.name}</h1>
          <ComputerStatusIndicator status={computer.status} preparing={isComputerPreparing(computer)} className="text-xs text-muted-foreground" />
          {connected && <p role="status" className="text-xs text-muted-foreground">
            {t(state.role === 'control' ? 'computer.cloud.controlling' : 'computer.cloud.viewing')}
          </p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <WorkspaceFiles workspaces={workspaces} selectedId={selectedId} />
          {!running && <ComputerPower computer={computer} power={power} sleep={sleep} />}
          {active && <Button size="sm" variant="outline" onClick={disconnect}>{t('computer.cloud.disconnect')}</Button>}
          {connected && document.fullscreenEnabled && (
            <Button type="button" size="sm" variant="outline" onClick={() => void toggleFullscreen()}>
              <Maximize2 aria-hidden="true" /> {t('computer.cloud.fullscreen')}
            </Button>
          )}
        </div>
      </div>
      {fullscreenError && <p role="alert" className="text-sm text-destructive">{t('computer.cloud.fullscreenFailed')}</p>}
      {power.error && power.variables?.computerId === computer.computer_id && (
        <p role="alert" className="text-sm text-destructive">{formatApiErrorDetail(power.error)}</p>
      )}
      <div className="relative grid min-h-[360px] grow place-items-center overflow-hidden rounded-lg border bg-card">
        <div ref={vnc} className={cn('absolute inset-0', connected && state.role === 'control' ? 'visible' : 'invisible')} />
        <img ref={picture} className={cn('absolute inset-0 h-full w-full object-contain', connected && state.role === 'view' ? 'visible' : 'invisible')}
          alt={t('computer.cloud.previewAlt', { name: computer.name })} />
        {connecting && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader size={14} /> {t(state.status === 'reconnecting' ? 'computer.cloud.reconnecting' : 'computer.cloud.connecting')}
          </p>
        )}
        {!active && (
          <div className="grid max-w-md justify-items-center gap-4 p-6 text-center text-sm text-muted-foreground">
            <Monitor className="size-8" aria-hidden="true" />
            {state.status === 'closed' && <p role="status">{t('computer.cloud.sessionEnded')}</p>}
            {state.status === 'revoked' && <p role="status">{t('computer.cloud.sessionRevoked')}</p>}
            {state.status === 'error' && <p role="alert" className="text-destructive">{state.message ?? t('computer.cloud.connectFailed')}</p>}
            {!computer.desktop_transport && <p>{t('computer.cloud.noDesktop')}</p>}
            {!!computer.desktop_transport && !running && <p>{t('computer.cloud.wakeFirst')}</p>}
            {!!computer.desktop_transport && running && (
              state.status === 'busy' ? (
                <>
                  <p role="status">{t('computer.cloud.controlBusy')}</p>
                  <Button onClick={() => void connect('control', true)}>{t('computer.cloud.takeover')}</Button>
                </>
              ) : (
                <div className="flex flex-wrap justify-center gap-2">
                  <Button onClick={() => void connect('control')}>{t('computer.cloud.control')}</Button>
                  <Button variant="outline" onClick={() => void connect('view')}>{t('computer.cloud.view')}</Button>
                </div>
              )
            )}
          </div>
        )}
      </div>
    </section>
  );
}

export default function Computers() {
  const { t } = useTranslation();
  const { computerId } = useParams();
  const [search] = useSearchParams();
  const [sshId, setSshId] = useState<string | null>(null);
  const { panel, specComputerId } = useComputersPanel();
  const list = useComputers({ refreshRunning: true });
  const { data: providerData } = useComputerProviders({ enabled: true });
  const { data: workspaceData } = useAllWorkspaces({ includeHome: true });
  const { power } = useComputerActions();
  useComputerStatusFanout();
  const computers = liveComputers(list.data?.computers);
  const now = useNow(1_000, computers.some((computer) => !!computer.running_since) && !computerId);
  const computer = computers.find((row) => row.computer_id === computerId);
  const sshComputer = computers.find((row) => row.computer_id === sshId && row.status === 'running');
  const workspacesFor = (id: string) => (workspaceData?.workspaces ?? []).filter((workspace) => workspace.computer_id === id);
  const providerFor = (row: Computer) => providerData?.providers.find((provider) => provider.kind === row.kind);

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page">
      {computer ? (
        <Desktop key={computer.computer_id} computer={computer} workspaces={workspacesFor(computer.computer_id)}
          selectedId={search.get('workspace')} power={power} sleep={providerFor(computer)?.supports_sleep} />
      ) : (
        <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {computerId ? <Link className="inline-flex items-center gap-2 text-sm" to="/computers"><ArrowLeft className="size-4" /> {t('computer.computers')}</Link>
              : <h1 className="title-font text-2xl font-semibold">{t('computer.computers')}</h1>}
            {!computerId && (
              <Button onClick={() => openComputersPanel({ view: 'create' })}><Plus aria-hidden="true" /> {t('computer.cloud.add')}</Button>
            )}
          </div>
          {list.isPending ? (
            <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Loader size={18} /> {t('computer.cloud.loading')}</div>
          ) : list.isError && !list.data ? (
            <div className="flex items-center gap-3"><p role="alert" className="text-sm text-destructive">{t('computer.cloud.loadFailed')}</p><Button variant="outline" size="sm" onClick={() => void list.refetch()}>{t('computer.cloud.retry')}</Button></div>
          ) : computerId ? (
            <p className="text-sm text-muted-foreground">{t('computer.cloud.missing')}</p>
          ) : computers.length === 0 ? (
            <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">{t('computer.cloud.empty')}</p>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,320px),1fr))] gap-4">
              {computers.map((row) => (
                <ComputerTile key={row.computer_id} computer={row} provider={providerFor(row)}
                  workspaces={workspacesFor(row.computer_id)} now={now} power={power} onSsh={() => setSshId(row.computer_id)} />
              ))}
            </div>
          )}
        </main>
      )}
      {(!list.isPending || panel || specComputerId) && (
        <Suspense fallback={null}><ComputersDialogHost /></Suspense>
      )}
      {sshComputer && <ComputerSshDialog key={sshComputer.computer_id} computer={sshComputer} onClose={() => setSshId(null)} />}
    </div>
  );
}
