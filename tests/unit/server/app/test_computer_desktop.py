import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient, WebSocketDenialResponse

from src.server.app import computer_desktop as api
from src.server.app import computers
from src.server.dependencies.principal import Principal, get_principal
from src.server.services import desktop_gateway as gateway
from src.server.services import desktop_leases as leases


@pytest.fixture
def desktop(monkeypatch):
    computer_id = str(uuid4())
    row = {
        "computer_id": computer_id,
        "user_id": "owner",
        "provider_ref": "sandbox",
        "kind": "daytona",
        "status": "running",
        "desktop_state": "off",
    }
    issued = leases.Session(str(uuid4()), computer_id, "owner", "sandbox", "control", "novnc")

    @asynccontextmanager
    async def lock(_key):
        yield True

    runtime_api = SimpleNamespace(start_desktop=AsyncMock(), desktop_screenshot=AsyncMock(return_value=b"frame"))

    @asynccontextmanager
    async def runtime(_row, _provider_ref):
        yield runtime_api

    monkeypatch.setattr(computers, "get_computer", AsyncMock(return_value=row))
    monkeypatch.setattr(gateway, "get_computer", AsyncMock(return_value=row))
    monkeypatch.setattr(api, "try_own_session_lock", lock)
    monkeypatch.setattr(api, "_computer_manager", lambda: SimpleNamespace(computer_runtime=runtime))
    monkeypatch.setattr(api.desktop_sessions, "set_desktop_state", AsyncMock(return_value=True))
    monkeypatch.setattr(leases, "viewer_generation", AsyncMock())
    monkeypatch.setattr(leases, "issue", AsyncMock(return_value=(issued, "a" * 43)))
    monkeypatch.setattr(leases, "check", AsyncMock())
    monkeypatch.setattr(leases, "release", AsyncMock())
    redis = SimpleNamespace(eval=AsyncMock())
    monkeypatch.setattr(leases, "get_cache_client", lambda: SimpleNamespace(client=redis))

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_principal] = lambda: Principal(user_id="owner", auth="session")
    return SimpleNamespace(app=app, row=row, issued=issued, base=f"/api/v1/computers/{computer_id}",
                           redis=redis, runtime=runtime_api)


def test_owner_session_starts_display_before_issuing_ticket(desktop):
    client = TestClient(desktop.app)
    response = client.post(f"{desktop.base}/desktop/session", json={"role": "control"}, headers={
        "origin": "http://localhost:5173", "sec-fetch-site": "same-origin",
    })

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "ticket": "a" * 43,
        "session_id": desktop.issued.session_id,
        "transport": "novnc",
        "role": "control",
        "ws_url": f"/ws/v1/computers/{desktop.row['computer_id']}/desktop",
    }
    assert [args.args[1] for args in api.desktop_sessions.set_desktop_state.await_args_list] == ["starting", "ready"]
    leases.issue.assert_awaited_once_with(desktop.row, "control", "novnc", takeover=False)


@pytest.mark.parametrize("auth,user", [("session", "another-owner"), ("computer", "owner")])
def test_session_requires_owner_with_first_party_auth(desktop, auth, user):
    desktop.app.dependency_overrides[get_principal] = lambda: Principal(user_id=user, auth=auth)
    response = TestClient(desktop.app).post(f"{desktop.base}/desktop/session", json={"role": "view"})

    assert response.status_code == 403
    leases.issue.assert_not_awaited()


def test_history_reads_ended_sessions_without_starting_stopped_computer(desktop, monkeypatch):
    desktop.row["status"] = "stopped"
    started_at = datetime(2026, 11, 23, 15, 0, tzinfo=UTC)
    ended_at = datetime(2026, 11, 23, 15, 5, tzinfo=UTC)
    recent = AsyncMock(return_value=[{
        "session_id": desktop.issued.session_id, "role": "control",
        "started_at": started_at, "ended_at": ended_at, "end_reason": "revoked",
        "provider_ref": "internal-sandbox",
    }])
    monkeypatch.setattr(api.desktop_sessions, "recent_sessions", recent)

    response = TestClient(desktop.app).get(f"{desktop.base}/desktop/sessions")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == [{
        "session_id": desktop.issued.session_id, "role": "control",
        "started_at": "2026-11-23T15:00:00Z", "ended_at": "2026-11-23T15:05:00Z",
        "end_reason": "revoked",
    }]
    recent.assert_awaited_once_with(desktop.row["computer_id"], "owner")
    leases.issue.assert_not_awaited()


@pytest.mark.parametrize("auth,user", [("session", "another-owner"), ("computer", "owner")])
def test_history_requires_owner_with_first_party_auth(desktop, monkeypatch, auth, user):
    recent = AsyncMock()
    monkeypatch.setattr(api.desktop_sessions, "recent_sessions", recent)
    desktop.app.dependency_overrides[get_principal] = lambda: Principal(user_id=user, auth=auth)

    response = TestClient(desktop.app).get(f"{desktop.base}/desktop/sessions")

    assert response.status_code == 403
    recent.assert_not_awaited()


@pytest.mark.parametrize("auth,user", [("session", "another-owner"), ("computer", "owner")])
def test_preview_checks_owner_before_serving_cache(desktop, auth, user):
    desktop.row["desktop_state"] = "ready"
    desktop.app.dependency_overrides[get_principal] = lambda: Principal(user_id=user, auth=auth)
    response = TestClient(desktop.app).post(f"{desktop.base}/desktop/screenshot")

    assert response.status_code == 403
    desktop.redis.eval.assert_not_awaited()
    desktop.runtime.desktop_screenshot.assert_not_awaited()


def test_preview_reuses_a_short_lived_frame_and_keeps_http_no_store(desktop):
    desktop.row.update(desktop_state="ready", running_since="current boot")
    desktop.redis.eval.side_effect = [[b"capture", b"gen-1"], 1, [b"frame", b"frame"]]
    client = TestClient(desktop.app)
    path = f"{desktop.base}/desktop/screenshot"

    for _ in range(2):
        response = client.post(path)
        assert response.status_code == 200
        assert response.content == b"frame"
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "no-store"
    desktop.runtime.desktop_screenshot.assert_awaited_once()
    begin, finish, reuse = [call.args for call in desktop.redis.eval.await_args_list]
    assert begin[2:5] == finish[2:5] == reuse[2:5]
    assert finish[5:] == (b"gen-1", begin[5], b"frame", leases.PREVIEW_REUSE_SECONDS)


def test_preview_refuses_active_controller(desktop):
    desktop.row["desktop_state"] = "ready"
    desktop.redis.eval.return_value = [b"busy"]
    response = TestClient(desktop.app).post(f"{desktop.base}/desktop/screenshot")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "desktop_busy"
    desktop.runtime.desktop_screenshot.assert_not_awaited()


def test_preview_requests_wait_for_another_capture(desktop):
    desktop.row["desktop_state"] = "ready"
    desktop.redis.eval.return_value = [b"pending"]
    response = TestClient(desktop.app).post(f"{desktop.base}/desktop/screenshot")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"
    desktop.runtime.desktop_screenshot.assert_not_awaited()


def test_preview_discards_capture_if_lease_generation_changed(desktop):
    desktop.row["desktop_state"] = "ready"
    desktop.redis.eval.side_effect = [[b"capture", b"gen-1"], 0]
    response = TestClient(desktop.app).post(f"{desktop.base}/desktop/screenshot")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "desktop_busy"
    desktop.runtime.desktop_screenshot.assert_awaited_once()


def test_preview_drops_a_frame_when_the_computer_restarts(desktop):
    desktop.row.update(desktop_state="ready", running_since="first boot")
    computers.get_computer.side_effect = [desktop.row, {**desktop.row, "running_since": "next boot"}]
    desktop.redis.eval.return_value = [b"capture", b""]
    response = TestClient(desktop.app).post(f"{desktop.base}/desktop/screenshot")

    assert response.status_code == 409
    desktop.redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_cached_preview_key_changes_when_owner_instance_or_boot_changes(desktop):
    desktop.redis.eval.return_value = [b"capture", b""]
    original = await leases.begin_preview(desktop.row)
    assert isinstance(original, leases.PreviewCapture)

    for field in ("user_id", "provider_ref", "running_since"):
        updated = await leases.begin_preview({**desktop.row, field: "new value"})
        assert isinstance(updated, leases.PreviewCapture)
        assert updated.keys[:2] == original.keys[:2]
        assert updated.keys[2] != original.keys[2]


@pytest.mark.asyncio
async def test_large_preview_frames_can_be_served_without_caching(desktop):
    capture = leases.PreviewCapture(("holder", "generation", "preview"), b"", "claim")
    desktop.redis.eval.return_value = 1
    await leases.finish_preview(capture, b"x" * (leases.PREVIEW_MAX_BYTES + 1))

    assert desktop.redis.eval.await_args.args[-2] == b""


def test_websocket_requires_origin_and_consumes_ticket_once(desktop, monkeypatch):
    desktop.row["desktop_state"] = "ready"
    redeem = AsyncMock(side_effect=[desktop.issued, None])
    monkeypatch.setattr(leases, "redeem", redeem)

    async def serve(ws, _manager, _row, _session):
        await ws.accept(subprotocol="dsalpha.desktop")
        await ws.send_bytes(b"frame")

    monkeypatch.setattr(gateway, "serve", serve)
    client = TestClient(desktop.app)
    path = f"/ws/v1/computers/{desktop.row['computer_id']}/desktop"
    protocols = ["dsalpha.desktop", "a" * 43]
    with (
        pytest.raises(WebSocketDenialResponse) as denied,
        client.websocket_connect(path, subprotocols=protocols, headers={"origin": "https://other.test"}),
    ):
        pytest.fail("foreign Origin was admitted")
    assert denied.value.status_code == 403
    redeem.assert_not_awaited()

    with client.websocket_connect(path, subprotocols=protocols, headers={"origin": "http://testserver"}) as ws:
        assert ws.accepted_subprotocol == "dsalpha.desktop"
        assert ws.receive_bytes() == b"frame"
    with (
        pytest.raises(WebSocketDenialResponse) as replay,
        client.websocket_connect(path, subprotocols=protocols, headers={"origin": "http://testserver"}),
    ):
        pytest.fail("a spent ticket was admitted")
    assert replay.value.status_code == 401
    leases.release.assert_awaited_once_with(desktop.issued.computer_id, desktop.issued.session_id)


@pytest.mark.asyncio
async def test_ticket_is_revoked_when_same_provider_ref_has_a_new_run(desktop):
    desktop.row.update(desktop_state="ready", running_since="a more recent run")
    with pytest.raises(leases.DesktopRevoked):
        await gateway.live_computer(desktop.issued)


@pytest.mark.asyncio
async def test_upstream_eof_is_a_connection_failure(desktop):
    async def frames():
        yield b"last frame"

    ws = SimpleNamespace(send_bytes=AsyncMock())
    traffic = gateway.Traffic()

    with pytest.raises(ConnectionError, match="Desktop upstream closed"):
        await gateway._desktop_output(ws, desktop.issued, frames(), traffic)

    ws.send_bytes.assert_awaited_once_with(b"last frame")
    assert traffic.sent == len(b"last frame")


@pytest.mark.asyncio
async def test_viewer_input_has_no_upstream(desktop):
    view = leases.Session(desktop.issued.session_id, desktop.issued.computer_id,
                          "owner", "sandbox", "view", "screenshot")
    ws = SimpleNamespace(receive=AsyncMock(return_value={"type": "websocket.receive", "bytes": b"input"}))
    runtime = SimpleNamespace(desktop_preview=AsyncMock(), desktop_screenshot=asyncio.Event().wait)

    with pytest.raises(leases.DesktopRevoked):
        await gateway._relay(ws, view, runtime, gateway.Traffic())

    runtime.desktop_preview.assert_not_awaited()
