"""Connected apps routes: setup, connect, disconnect and the page's payload.

The handlers are thin on purpose — the service owns Composio — so these pin the
status codes a page renders and that a failed setup never claims configured.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.server.app import connected_apps as api
from src.server.dependencies.principal import Principal
from src.server.models.connected_apps import ConnectRequest, ConnectedAppKeyRequest
from src.server.services import connected_apps

PRINCIPAL = Principal(user_id="u-1", auth="pat")


@pytest.mark.asyncio
async def test_status_returns_the_catalog_and_setup_state():
    with patch.object(
        api.connected_apps,
        "status",
        AsyncMock(return_value=(True, False, [], None)),
    ):
        answer = await api.get_connected_apps(PRINCIPAL)

    assert answer.configured is True
    assert answer.using_deployment_key is False
    assert answer.apps == []


@pytest.mark.asyncio
async def test_a_bad_key_keeps_the_page_unconfigured():
    with (
        patch.object(
            api.connected_apps,
            "save_key",
            AsyncMock(side_effect=connected_apps.ConnectedAppsError("bad key", status=401)),
        ),
        patch.object(api.connected_apps, "status", AsyncMock()) as status,
    ):
        with pytest.raises(HTTPException) as caught:
            await api.save_connected_apps_key(PRINCIPAL, ConnectedAppKeyRequest(api_key="x"))
    assert caught.value.status_code == 400
    status.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_returns_the_link():
    with patch.object(
        api.connected_apps,
        "connect_app",
        AsyncMock(return_value="https://connect.example/oauth"),
    ) as connect:
        answer = await api.connect_connected_app(
            PRINCIPAL, "github", ConnectRequest(alias="work")
        )

    assert answer.url == "https://connect.example/oauth"
    connect.assert_awaited_once_with("u-1", "github", "work")


@pytest.mark.asyncio
async def test_disconnect_returns_ok():
    with patch.object(api.connected_apps, "disconnect_account", AsyncMock()) as disconnect:
        answer = await api.disconnect_connected_app(PRINCIPAL, "ca-1")

    assert answer == {"ok": True}
    disconnect.assert_awaited_once_with("u-1", "ca-1")
