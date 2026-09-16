"""HTTP surface for the WeChat channel: bind by QR, inspect, send by hand.

Kept deliberately small — bind, status, recent, send, unbind. The channel
itself is the poll loop; these endpoints exist so an operator can bind without
a shell, and so a failure is diagnosable from outside the process.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.gateway.wechat import get_channel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/wechat", tags=["WeChat Channel"])


class SendRequest(BaseModel):
    to: str = Field(..., min_length=1, description="WeChat peer id")
    text: str = Field(..., min_length=1, max_length=4000)


@router.get("/status")
async def wechat_status() -> dict[str, Any]:
    channel = get_channel()
    if channel is None:
        return {"enabled": False, "reason": "channel not running"}
    return {"enabled": True, **channel.status()}


@router.get("/qrcode")
async def wechat_qrcode() -> dict[str, Any]:
    """Fetch a QR to scan. Returns the value to poll with and the image link."""
    from src.gateway.ilink.models import ILinkError
    from src.gateway.ilink.qr import fetch_qr

    try:
        qr_value, image_url = await fetch_qr()
    except (ILinkError, httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"QR fetch failed: {exc}") from exc
    return {"qr_value": qr_value, "image_url": image_url}


@router.get("/qr-status")
async def wechat_qr_status(qr_value: str, base_url: str = "") -> dict[str, Any]:
    """Poll one bind attempt; on ``confirmed`` the channel starts using it.

    Binding writes through to the client immediately rather than waiting for a
    restart, because the loop re-reads credentials each tick.
    """
    from src.gateway.ilink.models import ILinkError, ILinkTimeoutError
    from src.gateway.ilink.qr import poll_qr

    channel = get_channel()
    try:
        result = await poll_qr(qr_value, base_url)
    except (ILinkError, httpx.HTTPError, RuntimeError, ValueError) as exc:
        # The status endpoint is a long poll: it holds the request until the
        # scan state changes, so a client-side timeout means "nothing yet",
        # not a failure. Reported as `wait` so a poller just goes round again.
        # (A bare timeout is classified by message too — the QR helper raises
        # the transport error rather than the timeout subclass.)
        if isinstance(exc, ILinkTimeoutError) or "timeout" in str(exc).lower():
            return {"status": "wait"}
        raise HTTPException(status_code=502, detail=f"QR status failed: {exc}") from exc

    payload: dict[str, Any] = {"status": result.status, "user_id": result.user_id}
    if result.redirect_base:
        payload["redirect_base"] = result.redirect_base
    if result.confirmed and channel is not None:
        await channel.state.bind(result.account_id, result.token, result.base_url)
        await channel.refresh_creds()
        payload["bound"] = True
        payload["account_id"] = result.account_id
        logger.info("wechat bound to account %s", result.account_id)
    return payload


@router.post("/unbind")
async def wechat_unbind() -> dict[str, Any]:
    channel = get_channel()
    if channel is None:
        raise HTTPException(status_code=503, detail="channel not running")
    await channel.state.unbind()
    await channel.refresh_creds()
    return {"bound": False}


@router.get("/recent")
async def wechat_recent(limit: int = 20) -> dict[str, Any]:
    """Last messages in and out — the channel's own view, for debugging."""
    channel = get_channel()
    if channel is None:
        raise HTTPException(status_code=503, detail="channel not running")
    limit = max(1, min(int(limit), 50))
    return {
        "messages": channel.state.recent[-limit:],
        "peers": [
            {
                "peer": p.peer,
                "thread_id": p.thread_id,
                "display_name": p.display_name,
                "messages": p.messages,
                "last_message_at": p.last_message_at,
            }
            for p in channel.state.peers.values()
        ],
    }


@router.post("/send")
async def wechat_send(body: SendRequest) -> dict[str, Any]:
    channel = get_channel()
    if channel is None:
        raise HTTPException(status_code=503, detail="channel not running")
    if not channel.state.bound:
        raise HTTPException(status_code=409, detail="no WeChat bot is bound")
    try:
        await channel.send(body.to, body.text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"send failed: {exc}") from exc
    return {"sent": True, "to": body.to}
