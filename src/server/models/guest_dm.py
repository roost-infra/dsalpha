"""Request/response models for the guest bot DM API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InviteCreate(BaseModel):
    bot_id: str = Field(description="The receiving bot the link is minted for.")
    expires_in_hours: int = Field(default=168, ge=1, le=24 * 30)
    max_uses: int = Field(default=1, ge=1, le=20)


class InviteInfo(BaseModel):
    invite_id: str
    bot_id: str
    expires_at: str | None = None
    max_uses: int = 1
    uses: int = 0
    status: str = "active"


class InviteMinted(InviteInfo):
    token: str
    url: str | None = None


class SendByInvite(BaseModel):
    from_bot_id: str = Field(description="The sender's bot; must belong to the caller.")
    invite_token: str = Field(description="The invite token or link from the receiving owner.")
    content: str
    kind: str = Field(default="message", description="message | request | question | notice")
    idem: str | None = Field(
        default=None, description="Repeat-safe key for a retried send."
    )


class SendResult(BaseModel):
    message_id: str
    status: str = Field(description="pending_accept | delivered | queued | failed")
    contact_status: str | None = None
    thread_id: str | None = None


class BotRef(BaseModel):
    bot_id: str = Field(description="The local bot acting on this request.")


class ContactInfo(BaseModel):
    owner_user_id: str
    bot_id: str
    peer_bot_id: str
    peer_user_id: str
    status: str
    invite_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    peer_bot_name: str | None = None
    peer_bot_status: str | None = None


class ContactList(BaseModel):
    contacts: list[ContactInfo] = Field(default_factory=list)


class RequestResult(BaseModel):
    contact_status: str
    peer_bot_id: str | None = None
    pending_messages: int = 0
    failed_messages: int = 0
