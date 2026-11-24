"""Browser entry points for a running computer's desktop and SSH access."""

import asyncio
import contextlib
import logging
import re
import shlex
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect, WebSocketState

from ptc_agent.core.sandbox.providers import provider_class
from src.config.env import PUBLIC_APP_URL
from src.config.settings import get_allowed_origins
from src.server.app.computers import _computer_manager, _owned_computer
from src.server.database import desktop_sessions
from src.server.database.session_lock import try_own_session_lock
from src.server.dependencies.principal import CurrentPrincipal
from src.server.services import desktop_gateway as gateway
from src.server.services import desktop_leases as leases
from src.server.services.ssh_computers import ssh_info

logger = logging.getLogger(__name__)
router = APIRouter()


def _owner_session(principal: CurrentPrincipal) -> str:
    if not principal.unlimited:
        raise HTTPException(403, "Sign in to open this computer.")
    return principal.user_id


def _browser_request(request: Request) -> None:
    origin = request.headers.get("origin")
    direct = f"{request.url.scheme}://{request.headers.get('host')}"
    site = request.headers.get("sec-fetch-site")
    # The dev proxy rewrites Host. Fetch Metadata still names the relationship
    # to the browser-facing URL and cannot be set by JavaScript.
    if site == "same-origin" or (origin and origin in {direct, PUBLIC_APP_URL, *get_allowed_origins()}):
        return
    if origin or site == "cross-site":
        raise HTTPException(403, "Untrusted desktop origin.")


http = APIRouter(prefix="/api/v1/computers", tags=["Computers"], dependencies=[Depends(_browser_request)])


class DesktopRequest(BaseModel):
    role: Literal["control", "view"]


class DesktopSessionSummary(BaseModel):
    session_id: UUID
    role: leases.Role
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None


async def _running(computer_id: UUID, user: str) -> dict:
    row = await _owned_computer(str(computer_id), user)
    if row["status"] != "running" or not row.get("provider_ref"):
        raise HTTPException(409, "Wake this computer first.")
    return row


def _transport(row: dict) -> str:
    transports = provider_class(row["kind"]).desktop_transports
    if not transports:
        raise HTTPException(409, "This computer has no browser desktop.")
    return transports[0]


@contextlib.contextmanager
def _errors(message: str):
    try:
        yield
    except leases.DesktopBusy:
        raise HTTPException(409, {
            "code": "desktop_busy", "message": "A browser has control of this desktop.",
        }) from None
    except leases.PreviewPending:
        raise HTTPException(429, "A desktop preview is being captured.", headers={"Retry-After": "2"}) from None
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - SDK and storage errors need the same redaction.
        # Provider exceptions may contain signed preview hostnames.
        logger.warning("Desktop request failed (%s)", type(exc).__name__)
        raise HTTPException(503, message) from None


async def _session(computer_id: UUID, user: str, role: leases.Role, *, takeover: bool):
    row = await _running(computer_id, user)
    _transport(row)
    with _errors("The desktop session store is unavailable."):
        if not takeover:
            await leases.viewer_generation(str(computer_id))
    with _errors("The desktop could not start. Check the computer's desktop packages and provider status."):
        async with try_own_session_lock(f"desktop:start:{computer_id}") as acquired:
            if not acquired:
                raise HTTPException(409, "The desktop is starting. Try again shortly.")
            row = await _running(computer_id, user)
            transport = _transport(row)
            if row["desktop_state"] != "ready":
                await _set_state(row, "starting", transport)
            try:
                async with (
                    asyncio.timeout(43),
                    _computer_manager().computer_runtime(row, str(row["provider_ref"])) as runtime,
                ):
                    await runtime.start_desktop()
                    # A launch acknowledgement alone does not prove the display can render.
                    await runtime.desktop_screenshot()
            except Exception:
                await desktop_sessions.set_desktop_state(row, "error", transport)
                raise
            await _set_state(row, "ready", transport)
    with _errors("The desktop session store is unavailable."):
        session, ticket = await leases.issue(
            row, role, "screenshot" if role == "view" else transport, takeover=takeover,
        )
    return JSONResponse({
        "ticket": ticket, "session_id": session.session_id, "role": role,
        "transport": session.transport, "ws_url": f"/ws/v1/computers/{computer_id}/desktop",
    }, headers={"Cache-Control": "no-store"})


async def _set_state(row: dict, state: str, transport: str) -> None:
    if not await desktop_sessions.set_desktop_state(row, state, transport):
        raise HTTPException(409, "The computer changed while opening its desktop.")


@http.post("/{computer_id}/desktop/session")
async def open_desktop(computer_id: UUID, request: DesktopRequest, user: str = Depends(_owner_session)):
    return await _session(computer_id, user, request.role, takeover=False)


@http.get("/{computer_id}/desktop/sessions", response_model=list[DesktopSessionSummary])
async def desktop_history(computer_id: UUID, response: Response, user: str = Depends(_owner_session)):
    await _owned_computer(str(computer_id), user)
    response.headers["Cache-Control"] = "no-store"
    with _errors("The desktop session history is unavailable."):
        return await desktop_sessions.recent_sessions(str(computer_id), user)


@http.post("/{computer_id}/desktop/takeover")
async def take_desktop(computer_id: UUID, user: str = Depends(_owner_session)):
    return await _session(computer_id, user, "control", takeover=True)


@http.delete("/{computer_id}/desktop/session/{session_id}", status_code=204)
async def end_desktop(computer_id: UUID, session_id: UUID, user: str = Depends(_owner_session)):
    await _owned_computer(str(computer_id), user)
    with _errors("The desktop session store is unavailable."):
        await leases.release(str(computer_id), str(session_id))
    return Response(status_code=204)


@http.post("/{computer_id}/desktop/screenshot")
async def screenshot(computer_id: UUID, user: str = Depends(_owner_session)):
    row = await _running(computer_id, user)
    _transport(row)
    if row.get("desktop_state") != "ready":
        raise HTTPException(409, "Open the desktop to start a preview.")
    with _errors("The desktop preview is unavailable."):
        preview = await leases.begin_preview(row)
        if isinstance(preview, bytes):
            frame = preview
        else:
            identity = leases.preview_identity(row)
            async with (
                asyncio.timeout(10),
                _computer_manager().computer_runtime(row, str(row["provider_ref"])) as runtime,
            ):
                frame = await runtime.desktop_screenshot()
            current = await _running(computer_id, user)
            if current.get("desktop_state") != "ready" or leases.preview_identity(current) != identity:
                raise HTTPException(409, "The computer changed while capturing the preview.")
            await leases.finish_preview(preview, frame)
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@http.get("/{computer_id}/ssh")
async def ssh_connection(computer_id: UUID, user: str = Depends(_owner_session)):
    row = await _running(computer_id, user)
    if not provider_class(row["kind"]).supports_ssh:
        raise HTTPException(409, "This provider does not offer SSH access.")
    own = ssh_info(row)
    if own:
        if own.tunnel:
            raise HTTPException(409, "This machine connects through the server's private tunnel.")
        command = shlex.join(["ssh", "-p", str(own.port), "-l", own.username, "--", own.host])
        minutes = None
    else:
        minutes = 10
        with _errors("The provider could not issue SSH access."):
            async with (
                asyncio.timeout(15),
                _computer_manager().computer_runtime(row, str(row["provider_ref"])) as runtime,
            ):
                command = await runtime.ssh_command(minutes)
    return JSONResponse({"command": command, "expires_in_minutes": minutes},
                        headers={"Cache-Control": "no-store"})


router.include_router(http)


async def _deny(ws: WebSocket, status: int) -> None:
    if "websocket.http.response" in ws.scope.get("extensions", {}):
        await ws.send_denial_response(Response(status_code=status))
    else:
        await ws.close(code=1008)


@router.websocket("/ws/v1/computers/{computer_id}/desktop")
@router.websocket("/api/v1/computers/{computer_id}/desktop/ws")
async def desktop_socket(ws: WebSocket, computer_id: UUID):
    scheme = "https" if ws.url.scheme == "wss" else "http"
    origin = ws.headers.get("origin")
    if not origin or origin not in {f"{scheme}://{ws.headers.get('host')}", PUBLIC_APP_URL}:
        return await _deny(ws, 403)
    protocols = ws.scope.get("subprotocols") or []
    if (len(protocols) != 2 or protocols[0] != "dsalpha.desktop"
            or not re.fullmatch(r"[a-zA-Z0-9_-]{43}", protocols[1])):
        return await _deny(ws, 401)
    session = None
    code = 1000
    status = 503
    try:
        session = await leases.redeem(str(computer_id), protocols[1])
        if not session:
            return await _deny(ws, 401)
        row = await gateway.live_computer(session)
        await leases.check(session, renew=True)
        await gateway.serve(ws, _computer_manager(), row, session)
    except leases.DesktopRevoked:
        code = 1008
        status = 403
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - Close the browser without exposing upstream credentials.
        logger.warning("Desktop socket failed (%s)", type(exc).__name__)
        code = 1011
    finally:
        if session:
            try:
                await leases.release(session.computer_id, session.session_id)
            except Exception as exc:  # noqa: BLE001 - The lease expires even if Redis is unreachable.
                logger.warning("Could not release desktop lease (%s)", type(exc).__name__)
        with contextlib.suppress(RuntimeError, OSError, WebSocketDisconnect):
            if ws.application_state == WebSocketState.CONNECTING:
                await _deny(ws, status)
            elif ws.application_state == WebSocketState.CONNECTED:
                await ws.close(code=code)
