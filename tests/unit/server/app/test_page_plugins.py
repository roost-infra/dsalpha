"""The built-in page-plugin switches: known ids only, the caller's own rows."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import create_test_app

MOD = "src.server.app.page_plugins"
NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def client():
    from src.server.app.page_plugins import router

    app = create_test_app(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def db(monkeypatch):
    from src.server.app import page_plugins

    fakes = {
        "list_user_page_plugins": AsyncMock(return_value=[]),
        "set_user_page_plugin": AsyncMock(
            return_value={"plugin_id": "market-center", "enabled": True, "updated_at": NOW}
        ),
    }
    for name, fake in fakes.items():
        monkeypatch.setattr(page_plugins, name, fake)
    return fakes


@pytest.mark.asyncio
async def test_lists_every_known_plugin_with_unset_ones_off(client, db):
    db["list_user_page_plugins"].return_value = [{"plugin_id": "market-center", "enabled": False}]
    response = await client.get("/api/v1/page-plugins")
    assert response.status_code == 200
    assert response.json() == {"plugins": [{"plugin_id": "market-center", "enabled": False}, {"plugin_id": "content-desk", "enabled": False}]}


@pytest.mark.asyncio
async def test_returns_the_saved_switch(client, db):
    db["list_user_page_plugins"].return_value = [
        {"plugin_id": "market-center", "enabled": True}
    ]
    response = await client.get("/api/v1/page-plugins")
    assert response.json()["plugins"][0]["enabled"] is True


@pytest.mark.asyncio
async def test_enables_a_known_plugin_for_the_caller(client, db):
    response = await client.patch(
        "/api/v1/page-plugins/market-center", json={"enabled": True}
    )
    assert response.status_code == 200
    assert response.json() == {"plugin_id": "market-center", "enabled": True}
    db["set_user_page_plugin"].assert_awaited_once_with(
        "test-user-123", "market-center", True
    )


@pytest.mark.asyncio
async def test_refuses_an_unknown_plugin_before_writing(client, db):
    response = await client.patch(
        "/api/v1/page-plugins/not-a-plugin", json={"enabled": True}
    )
    assert response.status_code == 404
    db["set_user_page_plugin"].assert_not_awaited()
