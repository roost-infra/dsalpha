# Guest bot DM: invite-gated messaging between accounts

Platform mode holds every user's bots in one deployment. A bot may reach a
bot owned by another account, but only through a link the receiving owner
minted, and the first message runs only after that owner accepts.

## Product decisions

1. **Invite-only discovery.** No directory, no global handle. A bot is
   reachable only by a token an owner created for that bot (`POST /api/v1/dm/invites`).
2. **The first message needs acceptance.** Until then the message row is
   `queued` with `payload.awaiting_accept = true`; no agent turn runs, so a
   stranger cannot spend the receiver's credits. Accepting delivers the held
   message(s); declining fails them.
3. **The receiving owner pays.** Delivery posts the turn as the receiving
   bot's owner (`bot_messages` → `post_notification_turn(user_id=bot["user_id"])`),
   so quota and usage land on the account whose bot answers.

## Flow

```
Alice's bot A                      Bob's bot B
     │  POST /api/v1/dm/invites (Bob, B) → dm_<token>
     │  send_via_invite(A, token, text)
     │ ──────────────────────────────▶  contact(pending), message queued (awaiting_accept)
     │                                   Bob: GET /api/v1/dm/requests
     │                                   POST /requests/A/accept  → contact accepted
     │ ◀──────────────────────────────  held message delivered as B's turn (Bob pays)
     │ ◀── reply_guest_message(message_id, text) → B→A guest message, A's turn (Alice pays)
```

The accept also writes a mirror contact row (`bot_id = A, peer = B`) so B's
reply can travel back without a second approval. Blocking sets both directions
to `blocked` and fails any held messages.

## Data

- `bot_dm_invites`: hashed token, target bot, owner, expiry, max uses, uses.
- `bot_dm_contacts`: directional consent (`pending` / `accepted` / `blocked`),
  one row per direction; the receiver's row is the delivery gate.
- `bot_messages`: new `from_user_id`, `from_name`, `external`; `from_type`
  gains `guest_bot`; `user_id` stays the receiving owner (inbox scope).

## API

| Endpoint | Caller | Purpose |
|---|---|---|
| `POST /api/v1/dm/invites` | receiving owner | mint a link for one bot |
| `GET /api/v1/dm/invites?bot_id=` | owner | list links (token never returned again) |
| `DELETE /api/v1/dm/invites/{id}` | owner | revoke |
| `POST /api/v1/dm/send` | sender owner | first/subsequent message through a token |
| `GET /api/v1/dm/requests` | receiving owner | pending first contacts |
| `POST /api/v1/dm/requests/{peer}/accept` | receiving owner | accept; delivers held messages |
| `POST /api/v1/dm/requests/{peer}/decline` | receiving owner | fail held messages, drop contact |
| `POST /api/v1/dm/contacts/{peer}/block` | receiving owner | block both directions |
| `GET /api/v1/dm/contacts?status=` | owner | accepted/blocked roster |
| `GET /api/v1/dm/sent` | sender owner | guest messages sent |

## Agent tools

- `send_invite_message(invite, content, kind)` — paste a link/token and reach
  that bot; the first message waits for acceptance.
- `reply_guest_message(message_id, content, kind)` — answer a guest message
  this thread received, through the mirror consent.

## Safety

- `awaiting_accept` rows are skipped by the retry sweeper and never consume an
  attempt.
- Rate limits per sender bot: `GUEST_DM_MAX_PER_MINUTE` (6) and
  `GUEST_DM_MAX_PER_DAY` (50); at most 3 held first messages per pair.
- Content cap 64 KB; kinds limited to `message|request|question|notice|reply`.
- Invite tokens are stored hashed; expiry, max uses and revoke are enforced by
  a single guarded `UPDATE` when the first contact is created.
- `PUBLIC_APP_URL` (optional) turns a token into a clickable link in API
  responses; without it only the token is returned.

## Deploying

`alembic upgrade head` adds migration 117. No config is required; the two rate
limits and `PUBLIC_APP_URL` are optional. The web UI is the next phase — until
then the API and the agent tools are usable directly.
