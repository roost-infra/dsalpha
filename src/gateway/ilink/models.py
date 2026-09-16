"""Wire types, protocol constants and pure helpers for Tencent's iLink Bot API.

Everything here is deliberately I/O-free: the request/response shapes are the
part of the port that must match the server byte for byte, so they are kept
testable in isolation. Field names mirror the JSON exactly (`to_user_id`,
`context_token`, `get_updates_buf`) because the iLink gateway rejects unknown
envelopes instead of ignoring them.

Ported from athena's Go implementation (`internal/gateway/ilink`), which is
itself verified against Hermes' `gateway/platforms/weixin.py`; when a constant
looks arbitrary, the comment names the upstream it came from.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from typing import Any

# ── Protocol constants (verified against Hermes weixin.py) ──

BASE_URL = "https://ilinkai.weixin.qq.com"

APP_ID = "bot"
# (2<<16)|(2<<8)|0 — mirrors Hermes ILINK_APP_CLIENT_VERSION
APP_CLIENT_VERSION = "131584"
CHANNEL_VERSION = "2.2.0"

EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"
EP_GET_CONFIG = "ilink/bot/getconfig"
EP_SEND_TYPING = "ilink/bot/sendtyping"
EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"

# Item types inside item_list.
ITEM_TEXT = 1
ITEM_VOICE = 3

# Message envelope fields.
MSG_TYPE_BOT = 2
MSG_STATE_FINISH = 2

TYPING_STATUS_START = 1
TYPING_STATUS_STOP = 2
# Hermes TypingTicketCache ttl_seconds — a ticket works for ~10 minutes.
TYPING_TICKET_TTL_SEC = 600.0

# ── Poll tuning (mirrors Hermes gateway) ──

LONG_POLL_TIMEOUT_MS = 35_000
CONFIG_TIMEOUT_MS = 10_000
MAX_CONSECUTIVE_FAILURES = 3
RETRY_DELAY_SEC = 2.0
BACKOFF_DELAY_SEC = 30.0
SESSION_EXPIRED_ERR_CODE = -14
SESSION_EXPIRED_PAUSE_SEC = 600.0
KEEPALIVE_INTERVAL_SEC = 25.0
CRED_CHECK_INTERVAL_SEC = 10.0
# Backoff before restarting a poll loop that crashed (panic recovery in Go).
POLL_RESTART_BACKOFF_SEC = 5.0

# ── Send tuning (mirrors Hermes WeixinAdapter) ──

MAX_MESSAGE_LENGTH = 2000  # iLink chunks at ~2048 chars
SEND_CHUNK_DELAY_SEC = 1.5
SEND_RETRIES = 4
RATE_LIMIT_ERR_CODE = -2  # iLink frequency limit — backoff and retry
SEND_RETRY_DELAY_SEC = 1.0
API_TIMEOUT_SEC = 15.0  # hermes API_TIMEOUT_MS

# client_id prefix is wire-visible only for server-side retry dedup; kept from
# the Go implementation so both clients dedupe against each other.
CLIENT_ID_PREFIX = "athena-weixin-"

# Soft cap on the per-peer context_token cache: beyond this the whole map is
# dropped (replies degrade to tokenless sends until each peer messages again)
# rather than growing without bound.
CTX_TOKENS_CAP = 4096

# The Go client reads at most 4 MiB of a response body; QR responses are
# smaller than that in practice and capped at 1 MiB.
RESPONSE_LIMIT = 4 << 20
QR_RESPONSE_LIMIT = 1 << 20

# Handler-side fallback reply when the message handler raises (Go hardcodes it).
HANDLER_ERROR_REPLY = "抱歉，处理消息时出错了，请稍后再试。"


# ── Errors ──


class ILinkError(Exception):
    """Base class for every iLink failure raised by this package."""


class ILinkHTTPError(ILinkError):
    """Transport-level failure or a non-200 response."""


class ILinkTimeoutError(ILinkHTTPError):
    """The request exceeded its client-side deadline.

    The long-poll path turns this into "no messages this round" rather than an
    error, so it must be distinguishable from a real transport failure.
    """


class ILinkAPIError(ILinkError):
    """The gateway answered 200 with a non-zero `errcode`/`ret`.

    The code attributes exist so callers can branch on the error-code
    semantics (`-14` session expired, `-2` rate limit) instead of matching on
    message text the way the Go poll loop had to.
    """

    def __init__(
        self,
        message: str,
        *,
        code: int,
        errmsg: str = "",
        ret: Any = None,
        endpoint: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.errmsg = errmsg
        self.ret = ret
        self.endpoint = endpoint


# ── Wire dataclasses ──


@dataclass(frozen=True, slots=True)
class Creds:
    """Bot credentials. `account_id` is the bot's own iLink user id."""

    account_id: str
    token: str
    base_url: str = BASE_URL


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """A message received from a WeChat user.

    `context_token` must be echoed on the next outbound message to `from_`
    (iLink delivery contract, cf. Hermes WeixinAdapter).
    """

    from_: str
    message_id: str
    msg_type: int
    text: str
    context_token: str = ""


@dataclass(frozen=True, slots=True)
class GetUpdatesResult:
    """One long-poll response: the new cursor, its messages, and the server's
    suggested hold time for the next poll (0 = keep the caller's setting)."""

    sync_buf: str
    messages: list[InboundMessage] = field(default_factory=list)
    suggested_timeout_ms: int = 0


@dataclass(frozen=True, slots=True)
class QRResult:
    """Outcome of one QR bind status poll."""

    status: str = "wait"  # wait | scaned | scaned_but_redirect | confirmed | expired
    account_id: str = ""
    token: str = ""
    base_url: str = BASE_URL
    user_id: str = ""
    # "https://<redirect_host>" when Tencent redirects the status poll after
    # scanning (Hermes: scaned_but_redirect). Subsequent polls must go there.
    redirect_base: str = ""

    @property
    def confirmed(self) -> bool:
        return self.status == QR_STATUS_CONFIRMED and bool(self.account_id and self.token)

    @property
    def creds(self) -> Creds | None:
        """Credentials for `set_creds` once the scan is confirmed."""
        if self.status != QR_STATUS_CONFIRMED:
            return None
        return Creds(account_id=self.account_id, token=self.token, base_url=self.base_url)


QR_STATUS_WAIT = "wait"
QR_STATUS_SCANED = "scaned"
QR_STATUS_SCANED_REDIRECT = "scaned_but_redirect"
QR_STATUS_CONFIRMED = "confirmed"
QR_STATUS_EXPIRED = "expired"


# ── Helpers ──


def random_uin() -> str:
    """`X-WECHAT-UIN`: base64 of a random uint32 rendered in decimal.

    The gateway uses this as a per-request nonce; the encoding (base64 of the
    *decimal string*, not of the raw bytes) mirrors Hermes exactly.
    """
    value = secrets.randbits(32)
    return base64.b64encode(str(value).encode("ascii")).decode("ascii")


def new_client_id() -> str:
    """A per-chunk idempotency key.

    Minted once per chunk, not per attempt, so a retry after a lost response
    dedupes server-side.
    """
    return CLIENT_ID_PREFIX + secrets.token_hex(16)


def err_code_of(body: dict[str, Any]) -> int:
    """First non-zero of `errcode` then `ret`; 0 when both are absent/zero.

    iLink reports failures inconsistently between the two fields depending on
    the endpoint, so every response must be checked through this.
    """
    for key in ("errcode", "ret"):
        value = body.get(key)
        if isinstance(value, bool):  # bools are ints in Python; never a code
            continue
        if isinstance(value, (int, float)) and int(value) != 0:
            return int(value)
    return 0


def is_stale_session_code(code: int, errmsg: str) -> bool:
    """Mirrors Hermes `_is_stale_session_ret`.

    `-14` always means the session is gone. `-2` means rate limit — except
    when the errmsg is literally "unknown error", which Hermes found is the
    stale-session marker there; a missing errmsg stays a rate limit.
    """
    if code == SESSION_EXPIRED_ERR_CODE:
        return True
    return code == RATE_LIMIT_ERR_CODE and errmsg.strip().lower() == "unknown error"


def split_text_chunks(text: str, max_len: int) -> list[str]:
    """Split into ≤`max_len`-**byte** chunks (iLink rejects oversized messages).

    Byte semantics are load-bearing: the limit is enforced by the gateway in
    UTF-8 bytes, so a chunk is cut at a newline when one is available, then
    backed off to a rune boundary so multi-byte characters stay intact.
    """
    raw = text.encode("utf-8")
    if len(raw) <= max_len:
        return [text]

    chunks: list[str] = []
    while len(raw) > max_len:
        cut = max_len
        newline = raw.rfind(b"\n", 0, cut)
        if newline > 0:
            cut = newline + 1
        # Back off to a rune boundary so multi-byte chars stay intact.
        while 0 < cut < len(raw) and raw[cut] & 0xC0 == 0x80:
            cut -= 1
        if cut <= 0:
            cut = max_len
        chunks.append(raw[:cut].decode("utf-8"))
        raw = raw[cut:]
    if raw:
        chunks.append(raw.decode("utf-8"))
    return chunks


def extract_text(msg: dict[str, Any]) -> str:
    """Plain text out of an `item_list` — text items first, then voice-to-text.

    The two passes (rather than one) are the Hermes behaviour: a voice item
    must not shadow a text item that comes later in the list.
    """
    items = msg.get("item_list")
    if not isinstance(items, list):
        return ""
    for entry in items:
        if isinstance(entry, dict) and _int_or(entry.get("type")) == ITEM_TEXT:
            text_item = entry.get("text_item")
            if isinstance(text_item, dict):
                text = _str_or(text_item.get("text"))
                if text:
                    return text
    for entry in items:
        if isinstance(entry, dict) and _int_or(entry.get("type")) == ITEM_VOICE:
            voice_item = entry.get("voice_item")
            if isinstance(voice_item, dict):
                text = _str_or(voice_item.get("text"))
                if text:
                    return text
    return ""


def message_from_wire(raw: Any, self_id: str) -> InboundMessage | None:
    """Parse one `msgs[]` entry, dropping unusable and self-echoed messages.

    iLink echoes the bot's own outbound messages back through getupdates, so
    the self-guard (cf. Hermes) is a protocol requirement, not a nicety.
    """
    if not isinstance(raw, dict):
        return None
    sender = _str_or(raw.get("from_user_id"))
    if not sender or sender == self_id:
        return None
    return InboundMessage(
        from_=sender,
        message_id=_str_or(raw.get("message_id")),
        msg_type=_int_or(raw.get("msg_type")),
        text=extract_text(raw),
        context_token=_str_or(raw.get("context_token")),
    )


def send_message_payload(to: str, text: str, client_id: str, context_token: str = "") -> dict[str, Any]:
    """The sendmessage envelope. `from_user_id` is sent empty by design."""
    msg: dict[str, Any] = {
        "from_user_id": "",
        "to_user_id": to,
        "client_id": client_id,
        "message_type": MSG_TYPE_BOT,
        "message_state": MSG_STATE_FINISH,
        "item_list": [{"type": ITEM_TEXT, "text_item": {"text": text}}],
    }
    if context_token:
        msg["context_token"] = context_token
    return {"msg": msg, "base_info": {"channel_version": CHANNEL_VERSION}}


def get_updates_payload(sync_buf: str) -> dict[str, Any]:
    return {"get_updates_buf": sync_buf, "base_info": {"channel_version": CHANNEL_VERSION}}


def get_config_payload(peer: str, context_token: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"ilink_user_id": peer}
    if context_token:
        payload["context_token"] = context_token
    return payload


def typing_payload(peer: str, ticket: str, start: bool) -> dict[str, Any]:
    return {
        "ilink_user_id": peer,
        "typing_ticket": ticket,
        "status": TYPING_STATUS_START if start else TYPING_STATUS_STOP,
    }


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _str_or(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _int_or(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0
