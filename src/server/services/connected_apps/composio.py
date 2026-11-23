"""Connected apps through Composio.

One Composio project key (the deployment's or the user's own, kept in the vault)
creates a Tool Router session per account. The session exposes a hosted MCP
endpoint; dsalpha turns that endpoint into an ordinary user MCP server named
``composio``, with its ``x-api-key`` header pointing at the vault secret. The
tools therefore ride the connector path that already exists — scoped, probed
and synced into every workspace — instead of a second tool transport.

OAuth is Composio's: a Toolkit link starts the browser flow, the provider's
token stays with Composio, and disconnecting deletes the connected account with
``revoke_on_delete=true``. No provider token ever reaches dsalpha.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from typing import Any, Optional

import httpx

from src.config.env import (
    COMPOSIO_API_KEY,
    CONNECTED_APPS_API_BASE,
    CONNECTED_APPS_PROXY_BASE_URL,
)
from src.server.database import connected_apps as installation_db
from src.server.database.mcp_servers import (
    create_catalog_server,
    get_catalog_server,
    set_catalog_server_enabled,
    set_catalog_server_new_workspace_default,
    update_catalog_server,
)
from src.server.database.user_vault_secrets import (
    create_user_secret,
    delete_user_secret,
    get_user_secret_names,
    get_user_secrets_decrypted,
    update_user_secret,
)
from src.server.models.connected_apps import ConnectedAccount, ConnectedApp

logger = logging.getLogger(__name__)

VAULT_SECRET = "COMPOSIO_API_KEY"
#: The managed broker's per-account bearer token. It is not the Composio key;
#: the server adds that upstream.
PROXY_SECRET = "COMPOSIO_CONNECTOR_TOKEN"
CONNECTOR_NAME = "composio"
CONNECTOR_DESCRIPTION = "Connected external apps through Composio"
CONNECTOR_INSTRUCTION = (
    "Use for external apps the user has connected (GitHub, Gmail, Slack, "
    "Notion and the rest). Tools appear as their Composio names, for example "
    "GITHUB_CREATE_AN_ISSUE or GMAIL_SEND_EMAIL. If a call reports a missing "
    "connection, ask the user to connect that app under Connected apps."
)
MAX_CATALOG_APPS = 100


class ConnectedAppsError(Exception):
    """An error the page can render; ``status`` is the upstream HTTP status."""

    def __init__(self, message: str, *, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


#: A small, curated catalog used when Composio's marketplace cannot be read.
#: Slugs are Composio's, so connecting one after the catalog recovers works.
CURATED: tuple[tuple[str, str, str, str], ...] = (
    ("github", "GitHub", "Issues, pull requests and code", "github.com"),
    ("gmail", "Gmail", "Read and send email", "mail.google.com"),
    ("googlecalendar", "Google Calendar", "Read and create events", "calendar.google.com"),
    ("googlesheets", "Google Sheets", "Read and update spreadsheets", "sheets.google.com"),
    ("googledrive", "Google Drive", "Browse and manage files", "drive.google.com"),
    ("slack", "Slack", "Read channels and post updates", "slack.com"),
    ("notion", "Notion", "Pages and databases", "notion.so"),
    ("linear", "Linear", "Issues and project tracking", "linear.app"),
    ("sentry", "Sentry", "Errors and alerts", "sentry.io"),
    ("discord", "Discord", "Messages and channels", "discord.com"),
    ("twitter", "X (Twitter)", "Read and post on X", "x.com"),
    ("reddit", "Reddit", "Browse and post", "reddit.com"),
)


def _base() -> str:
    return CONNECTED_APPS_API_BASE.rstrip("/")


def _headers(key: str, *, json: bool = False) -> dict[str, str]:
    headers = {"x-api-key": key}
    if json:
        headers["content-type"] = "application/json"
    return headers


def _upstream_error(response: httpx.Response, fallback: str) -> ConnectedAppsError:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        message = body.get("message") or body.get("error")
        if isinstance(message, dict):
            message = message.get("message")
        if isinstance(message, str) and message.strip():
            return ConnectedAppsError(message.strip()[:300], status=response.status_code)
    return ConnectedAppsError(f"{fallback} (HTTP {response.status_code})", status=response.status_code)


async def _request(
    method: str, path: str, key: str, *, json: bool = False, body: Any = None
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                f"{_base()}{path}",
                headers=_headers(key, json=json),
                json=body,
            )
    except httpx.HTTPError as exc:
        raise ConnectedAppsError("Could not reach Composio; try again.") from exc
    if response.status_code >= 400:
        raise _upstream_error(response, "Composio request failed")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ConnectedAppsError("Composio returned an unreadable answer.") from exc
    return payload if isinstance(payload, dict) else {}


def _trusted_mcp_url(url: str) -> bool:
    try:
        parsed = httpx.URL(url)
        base = httpx.URL(_base())
    except Exception:  # noqa: BLE001 - httpx raises its own invalid-URL type
        return False
    host = (parsed.host or "").lower()
    if parsed.scheme == "https" and (
        host == "composio.dev"
        or host.endswith(".composio.dev")
        or (base.scheme == "https" and host == (base.host or "").lower())
    ):
        return True
    # A self-hosted local gateway is the one non-https case, and only when it
    # is also the configured API base.
    return (
        parsed.scheme == "http"
        and host in {"localhost", "127.0.0.1", "[::1]"}
        and base.scheme == "http"
        and host == (base.host or "").lower()
    )


async def _vault_key(user_id: str) -> Optional[str]:
    try:
        names = await get_user_secret_names(user_id)
        if VAULT_SECRET in names:
            secrets = await get_user_secrets_decrypted(user_id, {VAULT_SECRET})
            if secrets.get(VAULT_SECRET):
                return secrets[VAULT_SECRET]
    except Exception:  # noqa: BLE001 - an unreadable vault must not 500 the status
        logger.warning("[connected-apps] could not read the vault", exc_info=True)
    return None


async def key_mode(user_id: str) -> tuple[Optional[str], bool]:
    """(key, managed). A user's own key is direct; the deployment's is proxied."""
    key = await _vault_key(user_id)
    if key:
        return key, False
    return (COMPOSIO_API_KEY or None), bool(COMPOSIO_API_KEY)


async def stored_key(user_id: str) -> Optional[str]:
    """The effective Composio key (kept for callers that only need it)."""
    key, _managed = await key_mode(user_id)
    return key


async def _save_secret(user_id: str, name: str, value: str, description: str) -> None:
    names = await get_user_secret_names(user_id)
    if name in names:
        await update_user_secret(user_id, name, value=value, description=description)
        return
    try:
        await create_user_secret(user_id, name, value, description)
    except Exception as exc:  # SecretExists from a race, or vault disabled
        if "already exists" in str(exc):
            await update_user_secret(user_id, name, value=value)
            return
        raise ConnectedAppsError(
            "The vault is not available; ask the operator to configure it."
        ) from exc


async def _save_key(user_id: str, key: str) -> None:
    await _save_secret(
        user_id, VAULT_SECRET, key, "Composio project key for Connected apps"
    )


async def _save_proxy_token(user_id: str, token: str) -> None:
    await _save_secret(
        user_id,
        PROXY_SECRET,
        token,
        "Connected apps connector token",
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _proxy_base() -> str:
    return CONNECTED_APPS_PROXY_BASE_URL.rstrip("/")


def _proxy_url() -> str:
    base = _proxy_base()
    if not base:
        raise ConnectedAppsError(
            "Managed Connected apps need CONNECTED_APPS_PROXY_BASE_URL "
            "(or PUBLIC_API_BASE_URL) so sandboxes can reach the proxy.",
            status=503,
        )
    return f"{base}/api/v1/connected-apps/mcp"


async def _proxy_token_for(user_id: str, installation: dict[str, Any]) -> str:
    """A fresh broker token whose hash the installation row keeps."""
    token = secrets.token_urlsafe(32)
    await _save_proxy_token(user_id, token)
    await installation_db.save_installation(
        user_id,
        composio_user_id=installation["composio_user_id"],
        session_id=installation["session_id"],
        mcp_url=installation["mcp_url"],
        proxy_token_hash=_token_hash(token),
    )
    return token


async def validate_key(key: str) -> None:
    key = key.strip()
    if not key.startswith("ak_"):
        raise ConnectedAppsError("Composio project keys start with ak_.", status=400)
    await _request("GET", "/toolkits?limit=1", key)


async def ensure_installation(
    user_id: str, key: str, *, managed: bool = False, recreate: bool = False
) -> dict[str, Any]:
    """The account's Composio session, created once and reused after that.

    A user's own key keeps the direct hosted MCP URL and its vault key header.
    The deployment's key goes through the server proxy: the connector carries a
    per-account bearer token, and the shared key stays in this process.
    """
    if managed and not _proxy_base():
        raise ConnectedAppsError(
            "Managed Connected apps need CONNECTED_APPS_PROXY_BASE_URL "
            "(or PUBLIC_API_BASE_URL) so sandboxes can reach the proxy.",
            status=503,
        )

    if not recreate:
        existing = await installation_db.get_installation(user_id)
        if existing:
            try:
                await _request(
                    "GET",
                    f"/tool_router/session/{existing['session_id']}",
                    key,
                )
            except ConnectedAppsError as exc:
                # A key from another project cannot read the old session; keep
                # it only on a transient upstream failure.
                if exc.status not in (401, 403, 404):
                    await _wire_connector(user_id, existing, managed)
                    return existing
            else:
                await _wire_connector(user_id, existing, managed)
                return existing

    composio_user_id = f"dsalpha_{uuid.uuid4().hex}"
    session = await _request(
        "POST",
        "/tool_router/session",
        key,
        json=True,
        body={
            "user_id": composio_user_id,
            "manage_connections": {
                "enable": True,
                "enable_wait_for_connections": True,
                "enable_connection_removal": True,
            },
            "multi_account": {
                "enable": True,
                "max_accounts_per_toolkit": 5,
                "require_explicit_selection": True,
            },
        },
    )
    session_id = session.get("session_id")
    mcp = session.get("mcp")
    mcp_url = mcp.get("url") if isinstance(mcp, dict) else None
    if not isinstance(session_id, str) or not session_id:
        raise ConnectedAppsError("Composio did not return a session id.")
    if not isinstance(mcp_url, str) or not _trusted_mcp_url(mcp_url):
        raise ConnectedAppsError("Composio returned an untrusted MCP endpoint.")

    if not managed:
        await _save_key(user_id, key)
    row = await installation_db.save_installation(
        user_id,
        composio_user_id=composio_user_id,
        session_id=session_id,
        mcp_url=mcp_url,
        proxy_token_hash=None,
    )
    if managed:
        await _proxy_token_for(user_id, row)
        row = await installation_db.get_installation(user_id) or row
    await _wire_connector(user_id, row, managed)
    return row


async def _wire_connector(
    user_id: str, installation: dict[str, Any], managed: bool
) -> None:
    """Point the one connector at the right endpoint for this key mode."""
    if managed:
        if not installation.get("proxy_token_hash"):
            await _proxy_token_for(user_id, installation)
        await _upsert_connector(
            user_id,
            _proxy_url(),
            {"Authorization": f"Bearer ${{vault:{PROXY_SECRET}}}"},
        )
        return
    await _upsert_connector(
        user_id,
        installation["mcp_url"],
        {"x-api-key": f"${{vault:{VAULT_SECRET}}}"},
    )


async def _upsert_connector(
    user_id: str, mcp_url: str, headers: dict[str, str]
) -> None:
    fields = {
        "transport": "http",
        "url": mcp_url,
        "headers": headers,
        "description": CONNECTOR_DESCRIPTION,
        "instruction": CONNECTOR_INSTRUCTION,
        "tool_exposure_mode": "summary",
        # tools/list needs the credential too: without resolving the vault on
        # discovery the connector would look empty and never register tools.
        "discovery_uses_secrets": True,
    }
    existing = await get_catalog_server(user_id, CONNECTOR_NAME)
    if existing:
        # `enabled` and `enabled_in_new_workspaces` are live-switch fields, not
        # catalog columns: update_catalog_server rejects them. Use the two
        # writers that also bump the config version existing workspaces read.
        await update_catalog_server(user_id, CONNECTOR_NAME, updates=fields)
        if not existing.get("enabled"):
            await set_catalog_server_enabled(user_id, CONNECTOR_NAME, True)
        if not existing.get("enabled_in_new_workspaces"):
            await set_catalog_server_new_workspace_default(
                user_id, CONNECTOR_NAME, True
            )
        return
    await create_catalog_server(
        user_id,
        CONNECTOR_NAME,
        **fields,
        enabled=True,
        enabled_in_new_workspaces=True,
    )


async def _accounts(user_id: str, key: str, installation: dict[str, Any]) -> list[dict[str, Any]]:
    payload = await _request(
        "GET",
        "/connected_accounts?limit=100&order_by=updated_at&order_direction=desc"
        f"&user_ids={installation['composio_user_id']}",
        key,
    )
    items = payload.get("items") or []
    return [item for item in items if isinstance(item, dict)]


async def catalog(user_id: str, key: str, installation: dict[str, Any]) -> list[ConnectedApp]:
    """The marketplace, annotated with the accounts this user already has."""
    try:
        accounts = await _accounts(user_id, key, installation)
    except ConnectedAppsError:
        # A least-privilege key may have sessions and toolkits but not the
        # connected-account listing. The marketplace still works; it just
        # cannot mark accounts until that permission is granted.
        logger.warning("[connected-apps] connected accounts unavailable", exc_info=True)
        accounts = []
    connected: dict[str, list[ConnectedAccount]] = {}
    for account in accounts:
        toolkit = account.get("toolkit")
        slug = toolkit.get("slug") if isinstance(toolkit, dict) else None
        if not isinstance(slug, str) or not slug:
            continue
        connected.setdefault(slug, []).append(
            ConnectedAccount(
                id=str(account.get("id") or ""),
                alias=account.get("alias") if isinstance(account.get("alias"), str) else None,
                status=str(account.get("status") or "unknown"),
            )
        )

    apps: list[ConnectedApp] = []
    try:
        payload = await _request("GET", "/toolkits?limit=100&sort_by=usage", key)
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug") or item.get("key")
            if not isinstance(slug, str) or not slug:
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            categories = meta.get("categories") or []
            names = [
                str(entry.get("name"))
                for entry in categories
                if isinstance(entry, dict) and entry.get("name")
            ] if isinstance(categories, list) else []
            apps.append(
                ConnectedApp(
                    slug=slug,
                    name=str(item.get("name") or slug),
                    description=str(meta.get("description") or item.get("description") or ""),
                    logo=meta.get("logo") if isinstance(meta.get("logo"), str) else None,
                    categories=names[:4],
                    connected=slug in connected,
                    accounts=connected.get(slug, []),
                )
            )
    except ConnectedAppsError:
        logger.warning("[connected-apps] marketplace unavailable; using curated list", exc_info=True)

    if not apps:
        apps = [
            ConnectedApp(
                slug=slug,
                name=name,
                description=description,
                logo=None,
                categories=[],
                connected=slug in connected,
                accounts=connected.get(slug, []),
            )
            for slug, name, description, _domain in CURATED
        ]
    apps.sort(key=lambda app: (not app.connected, app.name.lower()))
    return apps[:MAX_CATALOG_APPS]


async def status(user_id: str) -> tuple[bool, bool, list[ConnectedApp], Optional[str]]:
    """(configured, deployment_key, apps, error) for the page."""
    key, managed = await key_mode(user_id)
    if not key:
        return False, False, [], None
    try:
        installation = await ensure_installation(user_id, key, managed=managed)
        apps = await catalog(user_id, key, installation)
        return True, managed, apps, None
    except ConnectedAppsError as exc:
        return True, managed, [], str(exc)


async def connect_app(user_id: str, slug: str, alias: Optional[str]) -> str:
    key, managed = await key_mode(user_id)
    if not key:
        raise ConnectedAppsError("Connected apps are not configured yet.", status=400)
    installation = await ensure_installation(user_id, key, managed=managed)
    body: dict[str, Any] = {"toolkit": slug}
    if alias:
        body["alias"] = alias
    payload = await _request(
        "POST",
        f"/tool_router/session/{installation['session_id']}/link",
        key,
        json=True,
        body=body,
    )
    url = payload.get("redirect_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ConnectedAppsError("Composio returned no usable authorization link.")
    return url


async def disconnect_account(user_id: str, account_id: str) -> None:
    key, _managed = await key_mode(user_id)
    if not key:
        raise ConnectedAppsError("Connected apps are not configured yet.", status=400)
    await _request(
        "DELETE",
        f"/connected_accounts/{account_id}?revoke_on_delete=true",
        key,
    )


async def save_key(user_id: str, key: str) -> None:
    key = key.strip()
    await validate_key(key)
    existing = await installation_db.get_installation(user_id)
    if existing:
        # A re-entered key may be the same project. Reuse the session when this
        # key can still read it; a key from another project gets a new session
        # instead of leaving a connector pointing at an unreachable endpoint.
        try:
            await _request(
                "GET",
                f"/tool_router/session/{existing['session_id']}",
                key,
            )
            await _save_key(user_id, key)
            await _wire_connector(user_id, existing, managed=False)
            return
        except ConnectedAppsError as exc:
            if exc.status not in (401, 403, 404):
                raise
    await ensure_installation(user_id, key, managed=False, recreate=True)


async def disconnect_all(user_id: str) -> None:
    """Forget the installation and its connector; the vault secret stays so a
    reconnect reuses the same project."""
    await installation_db.delete_installation(user_id)
    existing = await get_catalog_server(user_id, CONNECTOR_NAME)
    if existing:
        from src.server.database.mcp_servers import set_catalog_server_enabled

        await set_catalog_server_enabled(user_id, CONNECTOR_NAME, False)
