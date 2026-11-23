"""Relay an owned computer's desktop while this browser holds its grant."""

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from src.server.database import desktop_sessions
from src.server.database.computer import get_computer
from src.server.preview_proxy.ws import ConnectOnce
from src.server.services import desktop_leases as leases

_logger = logging.getLogger(__name__)
# A signed preview hostname is a short-lived credential. Keep protocol debug
# dumps out of deployment logs even when the root logger is set to DEBUG.
_wire_log = logging.getLogger(__name__ + ".upstream")
_wire_log.setLevel(logging.WARNING)


@dataclass
class Traffic:
    received: int = 0
    sent: int = 0


async def live_computer(session: leases.Session) -> dict:
    row = await get_computer(session.computer_id)
    if (
        not row
        or row["user_id"] != session.user_id
        or row["status"] != "running"
        or row.get("desktop_state") != "ready"
        or str(row["provider_ref"]) != session.provider_ref
        or str(row.get("running_since") or "") != session.running_since
    ):
        raise leases.DesktopRevoked
    return row


async def _watch(manager, runtime, session: leases.Session, traffic: Traffic) -> None:
    loop = asyncio.get_running_loop()
    next_activity = loop.time()
    while True:
        await leases.check(session, renew=True)
        row = await live_computer(session)
        if loop.time() >= next_activity:
            async with asyncio.timeout(8):
                await runtime.desktop_heartbeat()
                if not await manager.keep_computer_alive(row, session.provider_ref, runtime=runtime):
                    raise leases.DesktopRevoked
                await desktop_sessions.record(session.session_id, traffic.received, traffic.sent)
            next_activity = loop.time() + 30
        await asyncio.sleep(5)


async def _first_ended(*coroutines) -> None:
    tasks = [asyncio.create_task(coro) for coro in coroutines]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _browser_input(ws, session, upstream, traffic) -> None:
    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            return
        data = msg.get("bytes")
        if upstream is None or data is None or len(data) > 1024 * 1024:
            raise leases.DesktopRevoked
        await leases.check(session)
        await upstream.send(data)
        traffic.received += len(data)


async def _desktop_output(ws, session, upstream, traffic) -> None:
    async for data in upstream:
        if not isinstance(data, bytes):
            raise leases.DesktopRevoked
        await leases.check(session)
        await ws.send_bytes(data)
        traffic.sent += len(data)


async def _pictures(ws, session, runtime, traffic) -> None:
    while True:
        await leases.check(session)
        image = await runtime.desktop_screenshot()
        await leases.check(session)
        await ws.send_bytes(image)
        traffic.sent += len(image)
        await asyncio.sleep(1)


async def _relay(ws, session, runtime, traffic) -> None:
    if session.role == "view":
        # The viewer never has a socket to the VNC server, even while alone.
        await _first_ended(_browser_input(ws, session, None, traffic),
                           _pictures(ws, session, runtime, traffic))
        return
    endpoint = await runtime.desktop_preview()
    parts = urlsplit(endpoint.url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
        raise ValueError("Invalid desktop preview origin")
    url = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc,
                      "/websockify", parts.query, ""))
    async with ConnectOnce(url, subprotocols=["binary"], proxy=None, compression=None,
                           open_timeout=10, max_size=4 * 1024 * 1024, max_queue=2,
                           logger=_wire_log, additional_headers=endpoint.auth_headers) as upstream:
        await _first_ended(_browser_input(ws, session, upstream, traffic),
                           _desktop_output(ws, session, upstream, traffic))


async def serve(ws: WebSocket, manager, row: dict, session: leases.Session) -> None:
    traffic = Traffic()
    reason = "disconnected"
    await desktop_sessions.opened(session)
    try:
        async with manager.computer_runtime(row, session.provider_ref) as runtime:
            await leases.check(session, renew=True)
            await ws.accept(subprotocol="dsalpha.desktop")
            await _first_ended(_watch(manager, runtime, session, traffic),
                               _relay(ws, session, runtime, traffic))
    except leases.DesktopRevoked:
        reason = "revoked"
        raise
    except (WebSocketDisconnect, asyncio.CancelledError):
        raise
    except Exception:
        reason = "unavailable"
        raise
    finally:
        try:
            await desktop_sessions.record(session.session_id, traffic.received, traffic.sent, reason=reason)
        except Exception as exc:  # noqa: BLE001 - Audit cleanup cannot prevent the socket closing.
            # The sweeper can close this row if the database was unavailable.
            _logger.warning("Could not close desktop session audit (%s)", type(exc).__name__)
