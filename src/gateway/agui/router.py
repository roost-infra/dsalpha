"""HTTP surface of the AG-UI gateway.

Two endpoints, both scoped to the calling user: a run, and the thread mint a
client wants before it can name one. There is no status/bind/unbind trio as the
WeChat channel has, because there is nothing durable to bind — a run either
happens or it does not.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from src.gateway.agui import enabled
from src.gateway.agui.channel import AguiChannel
from src.gateway.agui.models import RunAgentInput
from src.server.utils.api import CurrentUserId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agui", tags=["AG-UI Gateway"])

# Buffering anywhere in front of the app turns a token stream into one lump
# delivered at the very end, which is the thing streaming exists to avoid.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _require_enabled() -> None:
    """503 rather than a 404 for a gateway that is off.

    A 404 would read as "this server does not speak AG-UI"; the truth is that
    it does and has been switched off, and the two want different fixes.
    """
    if not enabled():
        raise HTTPException(
            status_code=503,
            detail="agui gateway is disabled (set AGUI_ENABLED=1 to serve it)",
        )


class ThreadCreateRequest(BaseModel):
    first_query: str = Field(..., min_length=1, max_length=4000)
    agent_mode: str = Field("ptc", pattern="^(ptc|flash)$")
    workspace_id: str = Field("", description="Required for ptc mode unless the "
                              "caller already has a workspace")


class ThreadCreateResponse(BaseModel):
    thread_id: str
    workspace_id: str


@router.get("/status")
async def agui_status(user_id: CurrentUserId) -> dict[str, Any]:
    return {"enabled": enabled()}


@router.post("/threads", response_model=ThreadCreateResponse, status_code=201)
async def agui_create_thread(
    body: ThreadCreateRequest, user_id: CurrentUserId
) -> ThreadCreateResponse:
    """Mint a thread, so a client can name its conversation before it runs."""
    _require_enabled()
    async with AguiChannel(user_id) as channel:
        thread_id, workspace_id = await channel.create_thread(
            body.first_query, body.agent_mode, body.workspace_id
        )
    return ThreadCreateResponse(thread_id=thread_id, workspace_id=workspace_id)


@router.post("/run")
async def agui_run(body: RunAgentInput, user_id: CurrentUserId) -> StreamingResponse:
    """Run one turn and stream it back as AG-UI events over SSE.

    The client is closed from a background task rather than by the generator,
    because a generator that is cancelled mid-stream still has to release the
    connection pool it was reading from.
    """
    _require_enabled()
    channel = AguiChannel(user_id)
    return StreamingResponse(
        channel.run(body),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
        background=BackgroundTask(channel.aclose),
    )
