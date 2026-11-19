"""Invite-gated bot-to-bot messaging across accounts.

The database layer (``src.server.database.guest_dm``) owns invites and
directional consent; this package owns the flow: minting a link, the first
message that waits behind a pending request, accepting it, and the reply path
that uses the mirror row written on accept.
"""

from src.server.services.guest_dm.flow import (
    GuestDmBlocked,
    GuestDmError,
    GuestDmInviteInvalid,
    GuestDmNotFound,
    GuestDmRateLimited,
    accept_request,
    block_peer,
    create_invite,
    decline_request,
    list_contacts,
    list_requests,
    reply_to_guest,
    send_via_invite,
)

__all__ = [
    "GuestDmBlocked",
    "GuestDmError",
    "GuestDmInviteInvalid",
    "GuestDmNotFound",
    "GuestDmRateLimited",
    "accept_request",
    "block_peer",
    "create_invite",
    "decline_request",
    "list_contacts",
    "list_requests",
    "reply_to_guest",
    "send_via_invite",
]
