import { Monitor } from 'lucide-react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';

import type { RouteLeaveGuard } from '../../contexts/RouteLeaveGuardContext';
import { useComputer } from '../../hooks/useComputers';
import { desktopPath } from '../../utils/computerPlatform';

export function FilePanelDesktopLink({ computerId, workspaceId, guardLeave }: {
  computerId: string;
  workspaceId: string;
  guardLeave: RouteLeaveGuard;
}) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { data: computer } = useComputer(computerId);
  if (!computer?.desktop_transport) return null;

  const label = t('computer.cloud.openDesktop');
  return (
    <button
      type="button"
      className="file-panel-icon-btn"
      title={label}
      aria-label={label}
      onClick={() => guardLeave(() => { void navigate(desktopPath(computerId, workspaceId)); })}
    >
      <Monitor className="h-4 w-4" aria-hidden="true" />
    </button>
  );
}
