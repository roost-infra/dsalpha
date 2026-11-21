"""Connected apps API: OAuth connections to external apps through Composio.

Endpoints (account-scoped):
- GET    /api/v1/connected-apps            the catalog, accounts and setup state
- PUT    /api/v1/connected-apps/key        save a Composio project key and open a session
- DELETE /api/v1/connected-apps/key        forget the installation and switch its connector off
- POST   /api/v1/connected-apps/{slug}/connect   return an OAuth link for one app
- DELETE /api/v1/connected-apps/accounts/{id}    disconnect one connected account

The provider token stays with Composio; dsalpha only ever holds the project key
in the vault and the account's session endpoint, and the OAuth link is returned
once to the browser that asked for it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.server.dependencies.principal import (
    ReadPrincipal,
    WorkspaceWritePrincipal,
)
from src.server.models.connected_apps import (
    ConnectLink,
    ConnectRequest,
    ConnectedAppKeyRequest,
    ConnectedAppsStatus,
)
from src.server.services import connected_apps

router = APIRouter(prefix="/api/v1/connected-apps", tags=["Connected apps"])


def _raise(exc: connected_apps.ConnectedAppsError) -> None:
    status = 400 if exc.status in (400, 401, 403, 404, 422) else 502
    raise HTTPException(status_code=status, detail=str(exc)) from None


@router.get("", response_model=ConnectedAppsStatus)
async def get_connected_apps(principal: ReadPrincipal) -> ConnectedAppsStatus:
    configured, deployment, apps, error = await connected_apps.status(principal.user_id)
    return ConnectedAppsStatus(
        configured=configured,
        using_deployment_key=deployment,
        apps=apps,
        error=error,
    )


@router.put("/key", response_model=ConnectedAppsStatus)
async def save_connected_apps_key(
    principal: WorkspaceWritePrincipal, body: ConnectedAppKeyRequest
) -> ConnectedAppsStatus:
    """Validate and store the project key, then open (or reopen) the session."""
    try:
        await connected_apps.save_key(principal.user_id, body.api_key)
    except connected_apps.ConnectedAppsError as exc:
        _raise(exc)
    configured, deployment, apps, error = await connected_apps.status(principal.user_id)
    return ConnectedAppsStatus(
        configured=configured,
        using_deployment_key=deployment,
        apps=apps,
        error=error,
    )


@router.delete("/key", response_model=ConnectedAppsStatus)
async def clear_connected_apps_key(principal: WorkspaceWritePrincipal) -> ConnectedAppsStatus:
    """Forget the installation and switch its connector off; the vault key stays
    so connecting again reuses the same Composio project."""
    try:
        await connected_apps.disconnect_all(principal.user_id)
    except connected_apps.ConnectedAppsError as exc:
        _raise(exc)
    return ConnectedAppsStatus(configured=False, using_deployment_key=False)


@router.post("/{slug}/connect", response_model=ConnectLink)
async def connect_connected_app(
    principal: WorkspaceWritePrincipal, slug: str, body: ConnectRequest | None = None
) -> ConnectLink:
    try:
        url = await connected_apps.connect_app(
            principal.user_id, slug, body.alias if body else None
        )
    except connected_apps.ConnectedAppsError as exc:
        _raise(exc)
    return ConnectLink(url=url)


@router.delete("/accounts/{account_id}")
async def disconnect_connected_app(
    principal: WorkspaceWritePrincipal, account_id: str
) -> dict[str, bool]:
    try:
        await connected_apps.disconnect_account(principal.user_id, account_id)
    except connected_apps.ConnectedAppsError as exc:
        _raise(exc)
    return {"ok": True}
