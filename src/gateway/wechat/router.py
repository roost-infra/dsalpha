"""HTTP surface for WeChat binding — scoped to the calling user.

Every endpoint here is about *your* bot. The QR you fetch binds to your
account, the status you poll is yours, and unbinding cannot touch anyone
else's. That scoping is the whole reason these are per-user: a shared binding
endpoint would let one user's scan rebind another user's channel.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.gateway.wechat import get_manager
from src.server.utils.api import CurrentUserId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/wechat", tags=["WeChat Channel"])


class SendRequest(BaseModel):
    to: str = Field(..., min_length=1, description="WeChat peer id")
    text: str = Field(..., min_length=1, max_length=4000)


def _manager():
    manager = get_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="channel not running")
    return manager


@router.get("/status")
async def wechat_status(user_id: CurrentUserId) -> dict[str, Any]:
    manager = get_manager()
    if manager is None:
        return {"enabled": False, "reason": "channel not running"}
    return {"enabled": True, **manager.status(user_id)}


@router.get("/qrcode")
async def wechat_qrcode(user_id: CurrentUserId) -> dict[str, Any]:
    """Fetch a QR for this user to scan.

    The value is an opaque poll token; no server-side state is kept, so the
    poll endpoint needs nothing but the token and the caller's identity.
    """
    from src.gateway.ilink.models import ILinkError
    from src.gateway.ilink.qr import fetch_qr

    try:
        qr_value, image_url = await fetch_qr()
    except (ILinkError, httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"QR fetch failed: {exc}") from exc
    return {"qr_value": qr_value, "image_url": image_url}


@router.get("/qr-status")
async def wechat_qr_status(
    user_id: CurrentUserId, qr_value: str, base_url: str = ""
) -> dict[str, Any]:
    """Poll one bind attempt. On ``confirmed`` this user's bot is attached."""
    from src.gateway.ilink.models import ILinkError, ILinkTimeoutError
    from src.gateway.ilink.qr import poll_qr

    try:
        result = await poll_qr(qr_value, base_url)
    except (ILinkError, httpx.HTTPError, RuntimeError, ValueError) as exc:
        # The status endpoint is a long poll: it holds the request until the
        # scan state changes, so a client-side timeout means "nothing yet",
        # not a failure. Reported as `wait` so a poller just goes round again.
        if isinstance(exc, ILinkTimeoutError) or "timeout" in str(exc).lower():
            return {"status": "wait"}
        raise HTTPException(status_code=502, detail=f"QR status failed: {exc}") from exc

    payload: dict[str, Any] = {"status": result.status, "user_id": result.user_id}
    if result.redirect_base:
        payload["redirect_base"] = result.redirect_base
    if result.confirmed:
        await _manager().bind(user_id, result.account_id, result.token, result.base_url)
        payload["bound"] = True
        payload["account_id"] = result.account_id
        logger.info("wechat bound for user %s to account %s", user_id, result.account_id)
    return payload


@router.post("/unbind")
async def wechat_unbind(user_id: CurrentUserId) -> dict[str, Any]:
    await _manager().unbind(user_id)
    return {"bound": False}


@router.get("/recent")
async def wechat_recent(user_id: CurrentUserId, limit: int = 20) -> dict[str, Any]:
    """This user's last messages in and out — the channel's own view."""
    binding = _manager().binding(user_id)
    if binding is None:
        return {"messages": [], "peers": []}
    limit = max(1, min(int(limit), 50))
    return {
        "messages": binding.recent[-limit:],
        "peers": [
            {
                "peer": p.peer,
                "thread_id": p.thread_id,
                "display_name": p.display_name,
                "messages": p.messages,
                "last_message_at": p.last_message_at,
            }
            for p in binding.peers.values()
        ],
    }


@router.post("/send")
async def wechat_send(user_id: CurrentUserId, body: SendRequest) -> dict[str, Any]:
    channel = _manager().get(user_id)
    if channel is None:
        raise HTTPException(status_code=409, detail="no WeChat bot is bound")
    try:
        await channel.send(body.to, body.text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"send failed: {exc}") from exc
    return {"sent": True, "to": body.to}
