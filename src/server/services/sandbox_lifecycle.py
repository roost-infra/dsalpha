"""Env-gated rollout of turning a sandbox off when its last turn ends.

The lifecycle change ships to named users/workspaces first: with neither list
set the hook is a no-op, so an unconfigured deployment keeps today's
long-running sandboxes. ``SANDBOX_LIFECYCLE_GRACE_SECONDS`` keeps a short window
in which a follow-up turn can reuse the still-warm sandbox.

The same rollout can be supplied as JSON at ``scripts/sandbox_lifecycle_rollout.json``
(``{"users": [...], "workspaces": [...], "grace_seconds": 60}``). That file is
mounted from the host in the compose deployment, where changing a container
environment variable means recreating the container; the file needs only the
backend restart a source deploy already does.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_ROLLOUT_FILE = Path(__file__).resolve().parents[3] / "scripts" / "sandbox_lifecycle_rollout.json"


def _ids(name: str) -> set[str]:
    return {part.strip() for part in os.getenv(name, "").split(",") if part.strip()}


def _file_rollout() -> dict:
    try:
        with _ROLLOUT_FILE.open() as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _rollout() -> tuple[set[str], set[str], float]:
    file_data = _file_rollout()
    users = _ids("SANDBOX_LIFECYCLE_USERS") | {
        str(value) for value in file_data.get("users", []) if str(value)
    }
    workspaces = _ids("SANDBOX_LIFECYCLE_WORKSPACES") | {
        str(value) for value in file_data.get("workspaces", []) if str(value)
    }
    grace_raw = os.getenv("SANDBOX_LIFECYCLE_GRACE_SECONDS")
    if grace_raw is None:
        grace_raw = file_data.get("grace_seconds", 60)
    try:
        grace = max(0.0, float(grace_raw))
    except (TypeError, ValueError):
        grace = 60.0
    return users, workspaces, grace


def lifecycle_rolled_out(
    user_id: str | None, workspace_ids: tuple[str, ...] | list[str] = ()
) -> bool:
    """True when this turn's owner is inside the enabled rollout."""
    users, workspaces, _ = _rollout()
    if not users and not workspaces:
        return False
    if user_id and str(user_id) in users:
        return True
    return any(str(workspace) in workspaces for workspace in workspace_ids or ())


def grace_seconds() -> float:
    """Delay between the turn's end and the stop, in seconds."""
    return _rollout()[2]
