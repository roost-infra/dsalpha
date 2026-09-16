# `src.gateway.ilink` — WeChat bot client (Tencent iLink Bot API)

Self-contained, async port of athena's Go iLink gateway
(`internal/gateway/ilink/`) . It talks to **`https://ilinkai.weixin.qq.com`**
for the WeChat conversation-open-platform bot protocol: QR scan-bind, long-poll
inbound messages, chunked outbound delivery, and the typing indicator.

Nothing outside this directory is required, and nothing outside it was touched
— wiring into the app is a separate step.

## Usage

```python
from src.gateway.ilink import Creds, ILinkClient, PollConfig, fetch_qr, poll_qr

# 1. Bind by QR (no credentials needed).
qr_value, qr_image_url = await fetch_qr()
#   ... show qr_image_url to the user, then:
result = await poll_qr(qr_value)                       # "wait" | "scaned" | ...
if result.redirect_base:                               # scaned_but_redirect
    result = await poll_qr(qr_value, result.redirect_base)
if result.confirmed:
    creds = result.creds                               # Creds(account_id, token, base_url)

# 2. Talk.
async with ILinkClient(creds.account_id, creds.token, creds.base_url) as client:
    await client.send_text(peer, "hello")

    async def handler(from_: str, text: str) -> str:
        return "reply text"          # "" / None sends nothing

    task = client.start_poll(
        provider=lambda: creds,                     # or None while unbound
        handler=handler,
        send_func=client.send_text,                 # None = replies are dropped
        cfg=PollConfig(),                           # zeros = production defaults
    )
    ...
    task.cancel()
```

`start_poll` returns the supervising `asyncio.Task`; cancel it to stop. The
credential provider is re-read every 10s, so a QR bind takes effect live and an
unbind parks the loop (no API traffic at all while unbound) — it never exits
permanently.

## Public API

| Name | Signature |
|---|---|
| `ILinkClient` | `(account_id="", token="", base_url=BASE_URL, *, transport=None, verify_tls=True, ctx_tokens_cap=4096, typing_ticket_ttl=600.0, http_timeout=None)` |
| `ILinkClient.creds` | `-> Creds` |
| `ILinkClient.set_creds` | `(account_id, token, base_url="") -> None` |
| `ILinkClient.send_text` | `async (to, text) -> None` |
| `ILinkClient.get_updates` | `async (sync_buf="", timeout_ms=0) -> GetUpdatesResult` |
| `ILinkClient.get_config` | `async () -> None` (NAT keepalive) |
| `ILinkClient.send_typing` | `async (to, start=True) -> None` |
| `ILinkClient.start_poll` | `(provider, handler, send_func=None, cfg=None) -> asyncio.Task[None]` |
| `ILinkClient.context_token_for` / `set_context_token` / `clear_context_token` | `(peer[, token])` |
| `ILinkClient.aclose` / `__aenter__` / `__aexit__` | `async` |
| `start_poll` | `(client, provider, handler, send_func=None, cfg=None) -> asyncio.Task[None]` |
| `PollConfig` | `(long_poll_timeout_ms=0, keepalive_sec=0.0, cred_check_sec=0.0, session_expired_pause_sec=0.0)` |
| `CredsProvider` | `() -> Creds \| tuple[str, str, str, bool] \| tuple[str, str, str] \| None` |
| `Handler` | `(from_: str, text: str) -> str \| None`, sync or async |
| `SendFunc` | `async (to: str, text: str) -> None` (raises on failure) |
| `fetch_qr` | `async (*, client=None, timeout=35.0) -> tuple[str, str]` |
| `poll_qr` | `async (qr_value, base_url="", *, client=None, timeout=15.0, guard=None) -> QRResult` |
| `assert_weixin_host` / `redirect_base_of` | `(url) -> None` / `(host) -> str` |
| `Deduper` | `is_seen(id)`, `add(id)`, `reset()` |
| pure helpers | `split_text_chunks(text, max_len)`, `extract_text(msg)`, `err_code_of(body)`, `is_stale_session_code(code, errmsg)`, `is_session_expired(exc)`, `normalize_creds(value)`, `new_client_id()`, `random_uin()` |
| wire types | `Creds`, `InboundMessage(from_, message_id, msg_type, text, context_token)`, `GetUpdatesResult(sync_buf, messages, suggested_timeout_ms)`, `QRResult(status, account_id, token, base_url, user_id, redirect_base)` |
| errors | `ILinkError` → `ILinkHTTPError` → `ILinkTimeoutError`, and `ILinkAPIError(code, errmsg, ret, endpoint)` |

Protocol constants (`BASE_URL`, `EP_*`, `MAX_MESSAGE_LENGTH`, `SEND_RETRIES`,
`SESSION_EXPIRED_ERR_CODE`, `QR_STATUS_*`, …) are re-exported from the package
root; every value is copied from the Go source, not re-derived.

## Wire protocol (as ported)

- **Base URL** `https://ilinkai.weixin.qq.com`, `base_url` always
  right-trimmed of `/`. `verify_tls=True` by default (see deviations).
- **Endpoints** (all `POST` unless noted):
  `ilink/bot/getupdates`, `ilink/bot/sendmessage`, `ilink/bot/getconfig`
  (also used as a `GET` keepalive and as the typing-ticket fetch),
  `ilink/bot/sendtyping`,
  `GET ilink/bot/get_bot_qrcode?bot_type=3`, `GET ilink/bot/get_qrcode_status?qrcode=<value>`.
- **Headers**: every request sends `iLink-App-Id: bot` and
  `iLink-App-ClientVersion: 131584`. POSTs add
  `Content-Type: application/json`, `AuthorizationType: ilink_bot_token` and
  `X-WECHAT-UIN` (base64 of a random uint32 rendered in **decimal**; fresh per
  request). `Authorization: Bearer <token>` is added only when a token exists.
- **sendmessage body**:
  `{"msg": {"from_user_id": "", "to_user_id": <peer>, "client_id":
  "athena-weixin-<32 hex>", "message_type": 2, "message_state": 2,
  "item_list": [{"type": 1, "text_item": {"text": ...}}], "context_token":
  <optional>}, "base_info": {"channel_version": "2.2.0"}}` — message fields
  live inside `msg`, never at the top level; `context_token` is omitted when
  unknown.
- **getupdates body**: `{"get_updates_buf": <cursor>, "base_info": {"channel_version": "2.2.0"}}`.
  Response: `ret`, `errcode`, `errmsg`, `get_updates_buf` (new cursor),
  `longpolling_timeout_ms` (server-suggested next hold), `msgs[]` with
  `from_user_id`, `message_id`, `msg_type`, `context_token`, `item_list[]`
  (`{"type": 1, "text_item": {"text"}}` for text, `{"type": 3, "voice_item":
  {"text"}}` for voice-to-text). Messages whose `from_user_id` is empty or
  equals the bot's own account id are dropped; each accepted message's
  `context_token` is cached per peer.
- **getconfig**: `GET` with no body for the keepalive; `POST {"ilink_user_id":
  <peer>, "context_token": <optional>}` to fetch `typing_ticket`.
- **sendtyping**: `{"ilink_user_id": <peer>, "typing_ticket": <ticket>, "status": 1|2}`
  (`1` start, `2` stop).
- **get_bot_qrcode response**: `qrcode` (poll token), `qrcode_img_content`
  (liteapp URL the user opens).
- **get_qrcode_status response**: `status` (`wait` | `scaned` |
  `scaned_but_redirect` | `confirmed` | `expired`, missing → `wait`),
  `ilink_bot_id`, `bot_token`, `baseurl` (empty → default host),
  `ilink_user_id`, `redirect_host` (→ `redirect_base = "https://" + host`).
- **Error codes**: `errcode` then `ret` are both checked (first non-zero wins).
  `-14` = session expired (send: drop the peer's `context_token` and retry that
  chunk once tokenless; poll: pause up to 600s). `-2` = rate limit — back off
  `3 × 1s` and retry — *except* `-2` with `errmsg="unknown error"`, which is a
  stale session (Hermes `_is_stale_session_ret`). Any other non-zero code is
  retried with linear backoff (4 retries).
- **Timing** (defaults, all from the Go constants): long poll 35s (+10s
  request margin), getconfig/typing 10s, sendmessage 15s, chunk delay 1.5s
  between chunks, 1s × attempt linear retry backoff, 3s × 1s rate-limit
  backoff, keepalive 25s, credential re-read 10s, QR fetch 35s, QR status 15s.
- **Chunking**: `MAX_MESSAGE_LENGTH = 2000` **bytes**; split prefers the last
  `\n` inside the window, then backs off to a UTF-8 boundary; `client_id` is
  minted once per chunk so retries dedupe server-side.

## Tests

```bash
uv run pytest src/gateway/ilink/test_ilink.py -q     # 71 tests, ~2s, no network
```

All HTTP goes through `httpx.MockTransport`; nothing here makes a real request.

## Deliberate deviations from the Go version

1. **`asyncio` cancellation replaces `context.Context`.** Callers cancel the
   task instead of cancelling a ctx; every sleep/await raises `CancelledError`
   exactly where Go returned `ctx.Err()`.
2. **Cooperative yield per poll iteration** (`await asyncio.sleep(0)`). Go's
   scheduler can preempt a hot goroutine; asyncio cannot. The loop is normally
   paced by the server holding the long poll open, but a gateway (or a mock)
   that answers `getupdates` instantly would otherwise spin forever without
   ever letting another task on the same loop run. `sleep(0)` costs no
   measurable latency and changes no protocol behaviour.
3. **TLS verification is ON by default** (`verify_tls=False` reproduces Go).
   The Go client sets `InsecureSkipVerify` because of a macOS CA-bundle
   problem; a TLS handshake to `ilinkai.weixin.qq.com` verifies cleanly against
   this machine's CA bundle (`curl` reports `ssl_verify_result=0`), so the
   secure default wins and the escape hatch remains for hosts that need it.
4. **No mutex.** Credential/cache mutation happens between awaits, which is
   atomic under one event loop; the Go version needs `sync.RWMutex` for the
   same guarantee. The *behaviour* (account change drops both caches, the
   context-token map resets wholesale at the cap) is identical — note this is
   not an LRU: exceeding `ctx_tokens_cap` drops every token, exactly as Go.
5. **Typed errors.** Go classified session expiry by substring-matching the
   error text (`errcode=-14`). `ILinkAPIError` carries `code`/`errmsg`, and
   `is_session_expired()` checks those first, falling back to the Go substring
   test for foreign exceptions. The Go message text is preserved verbatim.
6. **A failed final attempt always raises.** Go can `return lastErr` when
   `lastErr` is still nil (a stale-session retry triggered on the last
   attempt), reporting success for a chunk the gateway rejected. This port
   raises instead of silently dropping the chunk.
7. **`PollConfig.session_expired_pause_sec`** is exposed (a const in Go) purely
   so the 600s pause path is testable.
8. **`seq`-style extras left out**: the Go `wechat-mcp` service keeps its own
   in-memory queue and state file; that is application wiring, not protocol,
   so nothing of it is here.
9. **structlog** is used (the repo's convention) instead of an injected
   `*slog.Logger`; log *fields* mirror the Go ones (`to`, `code`, `errmsg`,
   `account`). No credential value is ever logged — `token` appears only in the
   Authorization header and in the untrusted `account|token` fingerprint used
   for change detection, which is never logged.

## Decisions worth flagging to the wiring engineer

- `CredsProvider` accepts `Creds`, a Go-style `(account_id, token, base_url,
  ok)` 4-tuple, a 3-tuple, or `None`; partial credentials count as unbound.
- `set_creds(account_id, token)` with an empty `base_url` falls back to the
  production host (Go parity), *not* to the previously configured host — pass
  `base_url` explicitly if you use a non-default host.
- `poll_qr` guards the host (SSRF) via `assert_weixin_host`; the module-level
  `qr_base_guard` is swappable for tests, and `poll_qr(..., guard=...)`
  overrides it per call. Both QR calls raise `ILinkTimeoutError` (a subclass of
  `ILinkHTTPError`) when the status long poll runs out of time — that means
  "nothing yet", not a failed bind.
- `QRResult.base_url` defaults to `BASE_URL` when the server sends none.
- `Handler` may be sync or async; a handler exception is logged and answered
  with the Chinese apology string from the Go implementation.

## Not ported / not verifiable here

- **No live traffic was run** — the protocol was ported from the Go source and
  its tests, not re-verified against Tencent. Endpoint paths, header names,
  field names, chunking and error codes are copied literally, so the first
  integration step should be a real `fetch_qr` + `poll_qr` bind.
- The Go `wechat-mcp` service's persistent state (JSON creds file, message
  queue, `watchQR` background poller) and the dashboard wiring are out of scope.
- The QR status endpoint's server-side semantics for `expired` (i.e. how long a
  code stays valid) are the caller's concern: Go starts a fresh `fetch_qr`
  rather than extending an expired one, and so should the wiring.
