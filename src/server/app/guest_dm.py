"""Guest bot DM API: invite links and cross-account bot contacts.

Discovery is invite-only: an owner mints a link for one of their bots, the
other account's bot sends the first message through it, and nothing reaches a
turn until the receiving owner accepts. See ``docs/guest-bot-dm.md``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from src.server.database import bot_messages as msg_db
from src.server.database import guest_dm as dm_db
from src.server.dependencies.principal import ReadPrincipal
from src.server.models.guest_dm import (
    BotRef,
    ContactInfo,
    ContactList,
    InviteCreate,
    InviteInfo,
    InviteMinted,
    RequestResult,
    SendByInvite,
    SendResult,
)
from src.server.services import guest_dm as guest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dm", tags=["Guest DM"])


def _refuse(exc: guest.GuestDmError) -> HTTPException:
    return HTTPException(
        status_code=exc.status,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.post("/invites", response_model=InviteMinted, status_code=201)
async def create_invite(principal: ReadPrincipal, body: InviteCreate) -> InviteMinted:
    try:
        result = await guest.create_invite(
            principal.user_id,
            body.bot_id,
            expires_in_hours=body.expires_in_hours,
            max_uses=body.max_uses,
        )
    except guest.GuestDmError as exc:
        raise _refuse(exc) from None
    return InviteMinted(**result)


@router.get("/invites", response_model=list[InviteInfo])
async def list_invites(
    principal: ReadPrincipal, bot_id: str | None = Query(default=None)
) -> list[InviteInfo]:
    rows = await dm_db.list_invites(principal.user_id, bot_id)
    return [InviteInfo(**row) for row in rows]


@router.delete("/invites/{invite_id}")
async def revoke_invite(principal: ReadPrincipal, invite_id: str) -> dict:
    if not await dm_db.revoke_invite(principal.user_id, invite_id):
        raise HTTPException(status_code=404, detail="invite not found")
    return {"invite_id": invite_id, "status": "revoked"}


@router.post("/send", response_model=SendResult, status_code=202)
async def send_by_invite(principal: ReadPrincipal, body: SendByInvite) -> SendResult:
    try:
        result = await guest.send_via_invite(
            principal.user_id,
            body.from_bot_id,
            body.invite_token,
            content=body.content,
            kind=body.kind,
            idem=body.idem,
        )
    except guest.GuestDmError as exc:
        raise _refuse(exc) from None
    return SendResult(**result)


@router.get("/requests", response_model=ContactList)
async def list_requests(principal: ReadPrincipal) -> ContactList:
    rows = await guest.list_requests(principal.user_id)
    return ContactList(contacts=[ContactInfo(**row) for row in rows])


@router.post("/requests/{peer_bot_id}/accept", response_model=RequestResult)
async def accept_request(
    principal: ReadPrincipal, peer_bot_id: str, body: BotRef
) -> RequestResult:
    try:
        result = await guest.accept_request(
            principal.user_id, body.bot_id, peer_bot_id
        )
    except guest.GuestDmError as exc:
        raise _refuse(exc) from None
    return RequestResult(**result)


@router.post("/requests/{peer_bot_id}/decline", response_model=RequestResult)
async def decline_request(
    principal: ReadPrincipal, peer_bot_id: str, body: BotRef
) -> RequestResult:
    try:
        result = await guest.decline_request(
            principal.user_id, body.bot_id, peer_bot_id
        )
    except guest.GuestDmError as exc:
        raise _refuse(exc) from None
    return RequestResult(**result)


@router.post("/contacts/{peer_bot_id}/block", response_model=RequestResult)
async def block_peer(
    principal: ReadPrincipal, peer_bot_id: str, body: BotRef
) -> RequestResult:
    try:
        result = await guest.block_peer(principal.user_id, body.bot_id, peer_bot_id)
    except guest.GuestDmError as exc:
        raise _refuse(exc) from None
    return RequestResult(**result)


@router.get("/contacts", response_model=ContactList)
async def list_contacts(
    principal: ReadPrincipal, status: str | None = Query(default=None)
) -> ContactList:
    rows = await guest.list_contacts(principal.user_id, status=status)
    return ContactList(contacts=[ContactInfo(**row) for row in rows])


@router.get("/sent")
async def list_sent(principal: ReadPrincipal, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    rows = await msg_db.list_sent_for_user(principal.user_id, limit=limit)
    return {"messages": rows}
