"""Connected apps: the Composio session, its MCP connector and its link flow.

The service is mostly a policy layer over three side effects — the vault, the
installation row and a user MCP server — so these tests pin which side effect
runs, with what, and that a failed upstream call does not leave a half-wired
connector behind.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.server.services.connected_apps import composio


@pytest.mark.asyncio
async def test_catalog_annotates_the_calls_own_accounts():
    accounts = [
        {"id": "ca-1", "toolkit": {"slug": "github"}, "status": "ACTIVE", "alias": "work"}
    ]
    payload = {
        "items": [
            {
                "slug": "github",
                "name": "GitHub",
                "meta": {"description": "Code", "categories": [{"name": "Developer tools"}]},
            },
            {"slug": "gmail", "name": "Gmail"},
        ]
    }
    with (
        patch.object(composio, "_accounts", AsyncMock(return_value=accounts)),
        patch.object(composio, "_request", AsyncMock(return_value=payload)),
    ):
        apps = await composio.catalog("u-1", "ak_key", {"composio_user_id": "dsalpha_1"})

    github = next(app for app in apps if app.slug == "github")
    assert github.connected is True
    assert github.accounts[0].alias == "work"
    assert github.categories == ["Developer tools"]
    gmail = next(app for app in apps if app.slug == "gmail")
    assert gmail.connected is False


@pytest.mark.asyncio
async def test_catalog_falls_back_to_the_curated_list():
    with (
        patch.object(composio, "_accounts", AsyncMock(return_value=[])),
        patch.object(
            composio,
            "_request",
            AsyncMock(side_effect=composio.ConnectedAppsError("down")),
        ),
    ):
        apps = await composio.catalog("u-1", "ak_key", {"composio_user_id": "dsalpha_1"})

    assert len(apps) == len(composio.CURATED)
    assert {app.slug for app in apps} >= {"github", "gmail", "slack"}


@pytest.mark.asyncio
async def test_connect_returns_the_oauth_link_and_names_the_toolkit():
    request = AsyncMock(return_value={"redirect_url": "https://connect.example/oauth"})
    with (
        patch.object(composio, "stored_key", AsyncMock(return_value="ak_key")),
        patch.object(
            composio,
            "ensure_installation",
            AsyncMock(return_value={"session_id": "s-1", "composio_user_id": "dsalpha_1"}),
        ),
        patch.object(composio, "_request", request),
    ):
        url = await composio.connect_app("u-1", "github", "work")

    assert url == "https://connect.example/oauth"
    request.assert_awaited_once()
    _method, path, key = request.await_args.args
    assert (_method, path, key) == (
        "POST",
        "/tool_router/session/s-1/link",
        "ak_key",
    )
    assert request.await_args.kwargs["body"] == {"toolkit": "github", "alias": "work"}


@pytest.mark.asyncio
async def test_disconnect_revokes_at_composio():
    request = AsyncMock(return_value={})
    with (
        patch.object(composio, "stored_key", AsyncMock(return_value="ak_key")),
        patch.object(composio, "_request", request),
    ):
        await composio.disconnect_account("u-1", "ca-1")

    _method, path, _key = request.await_args.args
    assert _method == "DELETE"
    assert path == "/connected_accounts/ca-1?revoke_on_delete=true"


@pytest.mark.asyncio
async def test_a_new_key_creates_a_session_and_registers_the_connector():
    upstream = AsyncMock(
        return_value={
            "session_id": "s-1",
            "mcp": {"type": "http", "url": "https://mcp.composio.dev/session/abc"},
        }
    )
    saved = AsyncMock(return_value={"user_id": "u-1", "session_id": "s-1"})
    connector = AsyncMock()
    with (
        patch.object(composio, "_request", upstream),
        patch.object(composio, "_save_key", AsyncMock()),
        patch.object(composio.installation_db, "get_installation", AsyncMock(return_value=None)),
        patch.object(composio.installation_db, "save_installation", saved),
        patch.object(composio, "_upsert_connector", connector),
    ):
        row = await composio.ensure_installation("u-1", "ak_key")

    assert row["session_id"] == "s-1"
    saved.assert_awaited_once()
    assert saved.await_args.kwargs["mcp_url"] == "https://mcp.composio.dev/session/abc"
    connector.assert_awaited_once_with("u-1", "https://mcp.composio.dev/session/abc")


@pytest.mark.asyncio
async def test_an_untrusted_mcp_endpoint_is_refused_before_anything_is_written():
    upstream = AsyncMock(
        return_value={
            "session_id": "s-1",
            "mcp": {"type": "http", "url": "https://evil.example/session"},
        }
    )
    saved = AsyncMock()
    with (
        patch.object(composio, "_request", upstream),
        patch.object(composio.installation_db, "get_installation", AsyncMock(return_value=None)),
        patch.object(composio.installation_db, "save_installation", saved),
    ):
        with pytest.raises(composio.ConnectedAppsError, match="untrusted"):
            await composio.ensure_installation("u-1", "ak_key")

    saved.assert_not_awaited()


@pytest.mark.asyncio
async def test_re_entering_a_working_key_keeps_the_existing_session():
    existing = {
        "session_id": "s-old",
        "mcp_url": "https://mcp.composio.dev/session/old",
    }
    with (
        patch.object(composio, "validate_key", AsyncMock()),
        patch.object(composio.installation_db, "get_installation", AsyncMock(return_value=existing)),
        patch.object(composio, "_request", AsyncMock(return_value={"session_id": "s-old"})),
        patch.object(composio, "_save_key", AsyncMock()),
        patch.object(composio, "_upsert_connector", AsyncMock()) as connector,
        patch.object(composio, "ensure_installation", AsyncMock()) as recreate,
    ):
        await composio.save_key("u-1", "ak_key")

    recreate.assert_not_awaited()
    connector.assert_awaited_once_with("u-1", "https://mcp.composio.dev/session/old")


@pytest.mark.asyncio
async def test_a_key_from_another_project_recreates_the_session():
    existing = {"session_id": "s-old", "mcp_url": "https://mcp.composio.dev/session/old"}
    with (
        patch.object(composio, "validate_key", AsyncMock()),
        patch.object(composio.installation_db, "get_installation", AsyncMock(return_value=existing)),
        patch.object(
            composio,
            "_request",
            AsyncMock(side_effect=composio.ConnectedAppsError("no", status=404)),
        ),
        patch.object(composio, "ensure_installation", AsyncMock()) as recreate,
    ):
        await composio.save_key("u-1", "ak_new")

    recreate.assert_awaited_once_with("u-1", "ak_new", recreate=True)
