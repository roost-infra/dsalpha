"""Self-contained WeChat bot client for Tencent's iLink Bot API.

Three pieces, each usable on its own:

- `ILinkClient` — authenticated HTTP: chunked `send_text`, long-poll
  `get_updates`, the `getconfig` keepalive and the typing indicator.
- `fetch_qr` / `poll_qr` — the unauthenticated QR bind flow.
- `start_poll` (or `ILinkClient.start_poll`) — the supervised inbound
  long-poll loop driving a `Handler`.

Async-only, over `httpx`: the poll loop holds a 35s request open, so a sync
client would need a thread per poll. Credentials stay in the client and never
reach a log line.

    async with ILinkClient(creds.account_id, creds.token) as client:
        task = client.start_poll(provider, handler, send_func=client.send_text)
        ...
        task.cancel()
"""

from .client import ILinkClient, is_timeout_error
from .models import (
    API_TIMEOUT_SEC,
    APP_CLIENT_VERSION,
    APP_ID,
    BASE_URL,
    CHANNEL_VERSION,
    CTX_TOKENS_CAP,
    EP_GET_BOT_QR,
    EP_GET_CONFIG,
    EP_GET_QR_STATUS,
    EP_GET_UPDATES,
    EP_SEND_MESSAGE,
    EP_SEND_TYPING,
    ITEM_TEXT,
    ITEM_VOICE,
    KEEPALIVE_INTERVAL_SEC,
    LONG_POLL_TIMEOUT_MS,
    MAX_MESSAGE_LENGTH,
    MSG_STATE_FINISH,
    MSG_TYPE_BOT,
    QR_STATUS_CONFIRMED,
    QR_STATUS_EXPIRED,
    QR_STATUS_SCANED,
    QR_STATUS_SCANED_REDIRECT,
    QR_STATUS_WAIT,
    RATE_LIMIT_ERR_CODE,
    SESSION_EXPIRED_ERR_CODE,
    TYPING_STATUS_START,
    TYPING_STATUS_STOP,
    Creds,
    GetUpdatesResult,
    ILinkAPIError,
    ILinkError,
    ILinkHTTPError,
    ILinkTimeoutError,
    InboundMessage,
    QRResult,
    err_code_of,
    extract_text,
    is_stale_session_code,
    new_client_id,
    random_uin,
    split_text_chunks,
)
from .poll import (
    CredsProvider,
    CredsSource,
    Deduper,
    Handler,
    PollConfig,
    PollLoop,
    SendFunc,
    is_session_expired,
    normalize_creds,
    start_poll,
)
from .qr import (
    QR_STATUS_TIMEOUT_SEC,
    QR_TIMEOUT_SEC,
    assert_weixin_host,
    fetch_qr,
    poll_qr,
    qr_base_guard,
    redirect_base_of,
)

__all__ = [
    # client
    "ILinkClient",
    "is_timeout_error",
    # poll
    "CredsProvider",
    "CredsSource",
    "Deduper",
    "Handler",
    "PollConfig",
    "PollLoop",
    "SendFunc",
    "is_session_expired",
    "normalize_creds",
    "start_poll",
    # qr
    "QR_TIMEOUT_SEC",
    "QR_STATUS_TIMEOUT_SEC",
    "assert_weixin_host",
    "fetch_qr",
    "poll_qr",
    "qr_base_guard",
    "redirect_base_of",
    # wire types
    "Creds",
    "GetUpdatesResult",
    "InboundMessage",
    "QRResult",
    "ILinkError",
    "ILinkHTTPError",
    "ILinkTimeoutError",
    "ILinkAPIError",
    "QR_STATUS_WAIT",
    "QR_STATUS_SCANED",
    "QR_STATUS_SCANED_REDIRECT",
    "QR_STATUS_CONFIRMED",
    "QR_STATUS_EXPIRED",
    # protocol constants a caller may need to reason about
    "BASE_URL",
    "APP_ID",
    "APP_CLIENT_VERSION",
    "CHANNEL_VERSION",
    "EP_GET_UPDATES",
    "EP_SEND_MESSAGE",
    "EP_GET_CONFIG",
    "EP_SEND_TYPING",
    "EP_GET_BOT_QR",
    "EP_GET_QR_STATUS",
    "ITEM_TEXT",
    "ITEM_VOICE",
    "MSG_TYPE_BOT",
    "MSG_STATE_FINISH",
    "TYPING_STATUS_START",
    "TYPING_STATUS_STOP",
    "LONG_POLL_TIMEOUT_MS",
    "KEEPALIVE_INTERVAL_SEC",
    "API_TIMEOUT_SEC",
    "MAX_MESSAGE_LENGTH",
    "CTX_TOKENS_CAP",
    "SESSION_EXPIRED_ERR_CODE",
    "RATE_LIMIT_ERR_CODE",
    # pure helpers, handy for tests and for parsing raw payloads
    "err_code_of",
    "extract_text",
    "is_stale_session_code",
    "new_client_id",
    "random_uin",
    "split_text_chunks",
]
