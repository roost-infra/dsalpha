"""Env-gated rollout of turning a sandbox off when its last turn ends.

The lifecycle change ships to named users/workspaces first: with neither list
set the hook is a no-op, so an unconfigured deployment keeps today's
long-running sandboxes. ``SANDBOX_LIFECYCLE_GRACE_SECONDS`` keeps a short window
in which a follow-up turn can reuse the still-warm sandbox.
"""

import logging
import os

logger = logging.getLogger(__name__)


def _ids(name: str) -> set[str]:
    return {part.strip() for part in os.getenv(name, "").split(",") if part.strip()}


def lifecycle_rolled_out(
    user_id: str | None, workspace_ids: tuple[str, ...] | list[str] = ()
) -> bool:
    """True when this turn's owner is inside the enabled rollout."""
    users = _ids("SANDBOX_LIFECYCLE_USERS")
    workspaces = _ids("SANDBOX_LIFECYCLE_WORKSPACES")
    if not users and not workspaces:
        return False
    if user_id and str(user_id) in users:
        return True
    return any(str(workspace) in workspaces for workspace in workspace_ids or ())


def grace_seconds() -> float:
    """Delay between the turn's end and the stop, in seconds."""
    raw = os.getenv("SANDBOX_LIFECYCLE_GRACE_SECONDS", "60")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 60.0
