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

import hashlib

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from src.config.env import COMPOSIO_API_KEY
from src.server.database import connected_apps as installation_db
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

#: A tool result (a pasted issue body, a canvas) can be large; an unbounded
#: proxy body is a memory lever for anything holding a connector token.
_MAX_MCP_BODY = 20 * 1024 * 1024


def _proxy_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Missing connector token")
    return token.strip()


def _forward_headers(request: Request) -> dict[str, str]:
    headers = {}
    for name in (
        "accept",
        "content-type",
        "mcp-session-id",
        "mcp-protocol-version",
        "mcp-method",
        "mcp-name",
        "last-event-id",
    ):
        value = request.headers.get(name)
        if value:
            headers[name] = value
    headers["x-api-key"] = COMPOSIO_API_KEY
    return headers


@router.api_route("/mcp", methods=["GET", "POST", "DELETE"])
async def composio_mcp_proxy(request: Request) -> StreamingResponse:
    """The managed broker's MCP endpoint.

    A sandbox authenticates with its per-account connector token. The server
    looks up that installation and forwards the MCP request to the Composio
    session, adding the deployment's shared key upstream. The key never enters
    a user's vault, prompt or connector row.
    """
    token = _proxy_token(request)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = await installation_db.get_installation_by_proxy_token(digest)
    if row is None:
        raise HTTPException(status_code=401, detail="Unknown connector token")
    if not COMPOSIO_API_KEY:
        raise HTTPException(status_code=503, detail="Composio is not configured")

    body = b""
    if request.method == "POST":
        body = await request.body()
        if len(body) > _MAX_MCP_BODY:
            raise HTTPException(status_code=413, detail="MCP request body too large")

    client = httpx.AsyncClient(timeout=None)
    upstream = client.build_request(
        request.method,
        row["mcp_url"],
        headers=_forward_headers(request),
        content=body or None,
    )
    try:
        response = await client.send(upstream, stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Composio MCP is unreachable") from None

    headers = {}
    for name in ("content-type", "mcp-session-id", "cache-control"):
        value = response.headers.get(name)
        if value:
            headers[name] = value
    return StreamingResponse(
        response.aiter_raw(),
        status_code=response.status_code,
        headers=headers,
        background=BackgroundTask(response.aclose),
    )


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
