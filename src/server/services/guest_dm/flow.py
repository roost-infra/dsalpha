"""Guest bot DM flow: invites, first-contact consent, and replies.

Decisions this implements (product choices, 2026-11-19):

- **Invite-only discovery.** There is no public directory and no global
  handle; a bot can only be reached by a token the receiving owner minted for
  that bot.
- **The first message needs the receiver's accept.** Until then the message row
  exists as ``queued`` with ``payload.awaiting_accept`` and no turn runs, so a
  stranger cannot spend the receiver's credits.
- **The receiver's owner pays.** Delivery posts the turn as the receiving bot's
  owner (``bot["user_id"]``), so quotas and usage land on the account whose bot
  answers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from src.server.database import bot_messages as msg_db
from src.server.database import bots as bot_db
from src.server.database import guest_dm as dm_db

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"(dm_[A-Za-z0-9_-]{16,})")
_KINDS = ("message", "request", "question", "notice", "reply")
MAX_CHARS = 64 * 1024
MAX_PENDING_PER_PAIR = 3
DEFAULT_INVITE_HOURS = 168
MAX_INVITE_HOURS = 24 * 30

MAX_PER_MINUTE = int(os.environ.get("GUEST_DM_MAX_PER_MINUTE", "6"))
MAX_PER_DAY = int(os.environ.get("GUEST_DM_MAX_PER_DAY", "50"))

#: Strong references for fire-and-forget deliveries; a bare create_task result
#: may be garbage-collected before it runs.
_BACKGROUND: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


class GuestDmError(Exception):
    """A refusal a route or tool can turn into a readable result."""

    status = 400
    code = "guest_dm_error"


class GuestDmInviteInvalid(GuestDmError):
    status = 404
    code = "invite_invalid"


class GuestDmNotFound(GuestDmError):
    status = 404
    code = "not_found"


class GuestDmBlocked(GuestDmError):
    status = 403
    code = "blocked"


class GuestDmRateLimited(GuestDmError):
    status = 429
    code = "rate_limited"


def extract_token(value: str) -> str | None:
    """Accept a raw token or a pasted link; return the token, or None."""
    match = _TOKEN_RE.search(value or "")
    return match.group(1) if match else None


def invite_url(token: str) -> str | None:
    base = os.environ.get("PUBLIC_APP_URL") or os.environ.get("APP_PUBLIC_URL")
    if not base:
        return None
    return f"{base.rstrip('/')}/dm/{token}"


async def _owned_bot(user_id: str, bot_id: Any) -> dict[str, Any]:
    bot = await bot_db.get_bot_for_user(user_id, bot_id)
    if bot is None:
        raise GuestDmNotFound("bot not found")
    return bot


async def create_invite(
    user_id: str,
    bot_id: Any,
    *,
    expires_in_hours: int = DEFAULT_INVITE_HOURS,
    max_uses: int = 1,
) -> dict[str, Any]:
    """Mint one invite for one of the caller's bots (the receiving side)."""
    bot = await _owned_bot(user_id, bot_id)
    hours = max(1, min(int(expires_in_hours or DEFAULT_INVITE_HOURS), MAX_INVITE_HOURS))
    token = dm_db.new_token()
    row = await dm_db.create_invite(
        user_id,
        bot["bot_id"],
        created_by=user_id,
        token_hash=dm_db.hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(hours=hours),
        max_uses=max(1, min(int(max_uses or 1), 20)),
    )
    return {
        "invite_id": row["invite_id"],
        "bot_id": str(bot["bot_id"]),
        "token": token,
        "url": invite_url(token),
        "expires_at": row.get("expires_at"),
        "max_uses": row.get("max_uses"),
        "uses": row.get("uses", 0),
        "status": row.get("status"),
    }


async def _rate_limit(sender_bot_id: str) -> None:
    if await dm_db.count_recent_external(sender_bot_id, seconds=60) >= MAX_PER_MINUTE:
        raise GuestDmRateLimited("too many guest messages; wait a minute")
    if await dm_db.count_recent_external(sender_bot_id, seconds=86400) >= MAX_PER_DAY:
        raise GuestDmRateLimited("daily guest message budget is spent")


async def _queue_message(
    *,
    target_owner: str,
    target_bot_id: str,
    sender: dict[str, Any],
    sender_owner: str,
    content: str,
    kind: str,
    payload: dict[str, Any],
    idem: str | None,
    in_reply_to: str | None = None,
) -> dict[str, Any]:
    message, _created = await msg_db.create_message(
        target_owner,
        from_type="guest_bot",
        from_id=str(sender["bot_id"]),
        to_bot_id=target_bot_id,
        kind=kind,
        content=content,
        payload=payload,
        idem=idem,
        in_reply_to=in_reply_to,
        from_user_id=sender_owner,
        from_name=str(sender.get("name") or "")[:64] or None,
        external=True,
    )
    return message


async def _deliver(message_id: Any) -> dict[str, Any]:
    from src.server.services.bot_messages.delivery import deliver_message

    return await deliver_message(message_id)


async def send_via_invite(
    user_id: str,
    from_bot_id: Any,
    invite_token: str,
    *,
    content: str,
    kind: str = "message",
    idem: str | None = None,
) -> dict[str, Any]:
    """Send one guest message; the first one queues behind the receiver's accept."""
    token = extract_token(invite_token)
    if token is None:
        raise GuestDmInviteInvalid("that is not an invite link")
    if kind not in _KINDS:
        raise GuestDmError(f"kind must be one of {_KINDS}")
    text = (content or "").strip()
    if not text:
        raise GuestDmError("content is empty")
    if len(text) > MAX_CHARS:
        raise GuestDmError(f"content is longer than {MAX_CHARS} bytes")

    sender = await _owned_bot(user_id, from_bot_id)
    if sender.get("status") != "active":
        raise GuestDmError("this bot is paused")

    invite = await dm_db.get_invite_by_hash(dm_db.hash_token(token))
    if invite is None:
        raise GuestDmInviteInvalid("this invite is expired, used up or revoked")
    target = await bot_db.get_bot(invite["bot_id"])
    if target is None:
        raise GuestDmInviteInvalid("the receiving bot no longer exists")
    if target.get("status") != "active":
        raise GuestDmInviteInvalid("the receiving bot is paused")

    await _rate_limit(str(sender["bot_id"]))

    target_id = str(target["bot_id"])
    sender_id = str(sender["bot_id"])
    contact = await dm_db.get_contact(target_id, sender_id)

    if contact is not None and contact.get("status") == "blocked":
        raise GuestDmBlocked("the receiving bot is not accepting messages from this bot")

    if contact is not None and contact.get("status") == "accepted":
        message = await _queue_message(
            target_owner=str(target["user_id"]),
            target_bot_id=target_id,
            sender=sender,
            sender_owner=user_id,
            content=text,
            kind=kind,
            payload={"invite_id": invite.get("invite_id")},
            idem=idem,
        )
        outcome = await _deliver(message["message_id"])
        return {
            "message_id": message["message_id"],
            "status": outcome.get("status"),
            "contact_status": "accepted",
            "thread_id": outcome.get("thread_id"),
        }

    # First contact: one invite use, a pending row, and a message held until
    # the receiver accepts. A retried first message (same idem) answers the
    # existing row without spending a second use; a contact already pending
    # adds to the held queue without minting another use.
    awaiting = await dm_db.list_awaiting(target_id, sender_id)
    if len(awaiting) >= MAX_PENDING_PER_PAIR:
        raise GuestDmRateLimited(
            "this bot already has pending first messages waiting for the receiver"
        )
    if contact is None:
        if not await dm_db.claim_invite_use(invite.get("invite_id")):
            raise GuestDmInviteInvalid("this invite is expired or used up")
        await dm_db.create_pending(
            str(target["user_id"]),
            target_id,
            sender_id,
            user_id,
            invite.get("invite_id"),
        )
    message = await _queue_message(
        target_owner=str(target["user_id"]),
        target_bot_id=target_id,
        sender=sender,
        sender_owner=user_id,
        content=text,
        kind=kind,
        payload={"invite_id": invite.get("invite_id"), "awaiting_accept": True},
        idem=idem,
    )
    return {
        "message_id": message["message_id"],
        "status": "pending_accept",
        "contact_status": "pending",
        "thread_id": None,
    }


async def _deliver_held(message_ids: list[str]) -> None:
    for message_id in message_ids:
        try:
            await _deliver(message_id)
        except Exception:  # a delivery failure keeps the row for the sweeper
            logger.exception("[GUEST_DM] deferred delivery of %s failed", message_id)


async def accept_request(user_id: str, bot_id: Any, peer_bot_id: Any) -> dict[str, Any]:
    """Accept a pending request; the held first messages are delivered after."""
    bot = await _owned_bot(user_id, bot_id)
    contact = await dm_db.get_contact(bot["bot_id"], peer_bot_id)
    if contact is None:
        raise GuestDmNotFound("no pending request from that bot")
    if contact.get("status") == "blocked":
        raise GuestDmBlocked("that bot is blocked")
    if contact.get("status") != "pending":
        return {"contact_status": contact.get("status"), "delivered": 0}
    accepted = await dm_db.accept_contact(user_id, bot["bot_id"], peer_bot_id)
    if accepted is None:
        raise GuestDmNotFound("no pending request from that bot")
    held = await dm_db.list_awaiting(str(bot["bot_id"]), str(peer_bot_id))
    if held:
        # Clear the hold synchronously so a crash before the task runs cannot
        # strand the message; the sweeper is then allowed to retry a busy
        # thread like any other delivery.
        await dm_db.clear_awaiting(str(bot["bot_id"]), str(peer_bot_id))
        # The accept route must return quickly; each delivery is a full agent
        # turn and may legitimately wait on a busy thread.
        _spawn(_deliver_held(held))
    return {
        "contact_status": "accepted",
        "pending_messages": len(held),
        "peer_bot_id": str(peer_bot_id),
    }


async def decline_request(user_id: str, bot_id: Any, peer_bot_id: Any) -> dict[str, Any]:
    bot = await _owned_bot(user_id, bot_id)
    contact = await dm_db.get_contact(bot["bot_id"], peer_bot_id)
    if contact is None:
        raise GuestDmNotFound("no pending request from that bot")
    failed = await dm_db.fail_awaiting(str(bot["bot_id"]), str(peer_bot_id))
    await dm_db.delete_contact(bot["bot_id"], peer_bot_id)
    return {"contact_status": "declined", "failed_messages": failed}


async def block_peer(user_id: str, bot_id: Any, peer_bot_id: Any) -> dict[str, Any]:
    bot = await _owned_bot(user_id, bot_id)
    await dm_db.fail_awaiting(str(bot["bot_id"]), str(peer_bot_id))
    await dm_db.block_pair(bot["bot_id"], peer_bot_id)
    return {"contact_status": "blocked", "peer_bot_id": str(peer_bot_id)}


async def reply_to_guest(
    user_id: str,
    from_bot_id: Any,
    message_id: Any,
    *,
    content: str,
    kind: str = "reply",
) -> dict[str, Any]:
    """Answer a guest message as the receiving bot, through the mirror consent."""
    sender = await _owned_bot(user_id, from_bot_id)
    original = await msg_db.get_message(message_id)
    if original is None:
        raise GuestDmNotFound("that message does not exist")
    if str(original.get("to_bot_id")) != str(sender["bot_id"]):
        raise GuestDmBlocked("that message was not addressed to this bot")
    if not original.get("external"):
        raise GuestDmError("that message is not a guest message")
    peer_id = str(original.get("from_id"))
    if not await dm_db.delivery_allowed(peer_id, sender["bot_id"]):
        raise GuestDmBlocked("the sending bot is no longer reachable")
    peer = await bot_db.get_bot(peer_id)
    if peer is None or peer.get("status") != "active":
        raise GuestDmNotFound("the sending bot no longer exists")
    text = (content or "").strip()
    if not text:
        raise GuestDmError("content is empty")
    if kind not in _KINDS:
        raise GuestDmError(f"kind must be one of {_KINDS}")
    message = await _queue_message(
        target_owner=str(peer["user_id"]),
        target_bot_id=peer_id,
        sender=sender,
        sender_owner=user_id,
        content=text,
        kind=kind,
        payload={"in_reply_to": str(original["message_id"])},
        idem=None,
        in_reply_to=str(original["message_id"]),
    )
    outcome = await _deliver(message["message_id"])
    return {
        "message_id": message["message_id"],
        "status": outcome.get("status"),
        "thread_id": outcome.get("thread_id"),
    }


async def _hydrate_contacts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        peer = await bot_db.get_bot(row["peer_bot_id"])
        item = dict(row)
        item["peer_bot_name"] = (peer or {}).get("name")
        item["peer_bot_status"] = (peer or {}).get("status")
        out.append(item)
    return out


async def list_contacts(
    user_id: str, *, status: str | None = None
) -> list[dict[str, Any]]:
    return await _hydrate_contacts(await dm_db.list_contacts(user_id, status=status))


async def list_requests(user_id: str) -> list[dict[str, Any]]:
    return await _hydrate_contacts(await dm_db.list_contacts(user_id, status="pending"))
