"""Async HTTP client for Tencent's iLink Bot API (ilinkai.weixin.qq.com).

Covers the three authenticated calls the bot needs — long-poll `getupdates`,
`sendmessage` delivery and the `getconfig`/`sendtyping` indicator pair — plus
the per-peer caches the protocol requires: every outbound reply must echo the
latest inbound `context_token` for that peer, and every typing indicator needs
a per-peer ticket that is minted via `getconfig` and expires after ~10 minutes.

Port of athena's `internal/gateway/ilink/client.go` + `typing.go`. Credentials
never reach a log line here: the token only ever travels in the Authorization
header, and the retry logs carry peer/code/errmsg only.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import httpx
import structlog

from .models import (
    API_TIMEOUT_SEC,
    APP_CLIENT_VERSION,
    APP_ID,
    BASE_URL,
    CONFIG_TIMEOUT_MS,
    CTX_TOKENS_CAP,
    EP_GET_CONFIG,
    EP_GET_UPDATES,
    EP_SEND_MESSAGE,
    EP_SEND_TYPING,
    LONG_POLL_TIMEOUT_MS,
    MAX_MESSAGE_LENGTH,
    RESPONSE_LIMIT,
    RATE_LIMIT_ERR_CODE,
    SEND_CHUNK_DELAY_SEC,
    SEND_RETRIES,
    SEND_RETRY_DELAY_SEC,
    TYPING_TICKET_TTL_SEC,
    Creds,
    GetUpdatesResult,
    ILinkAPIError,
    ILinkError,
    ILinkHTTPError,
    ILinkTimeoutError,
    TYPING_STATUS_START,
    TYPING_STATUS_STOP,
    err_code_of,
    get_config_payload,
    get_updates_payload,
    is_stale_session_code,
    message_from_wire,
    new_client_id,
    random_uin,
    send_message_payload,
    split_text_chunks,
    truncate,
    typing_payload,
)

if TYPE_CHECKING:
    from .poll import CredsProvider, Handler, PollConfig, SendFunc

logger = structlog.get_logger(__name__)


def is_timeout_error(exc: BaseException) -> bool:
    """Whether `exc` is a client-side timeout (the long-poll window elapsed).

    Kept in addition to `ILinkTimeoutError` so a caller holding an exception
    from a foreign layer (raw httpx, httpcore) classifies it the same way.
    """
    return isinstance(exc, (ILinkTimeoutError, httpx.TimeoutException, TimeoutError))


class ILinkClient:
    """An authenticated iLink bot client.

    Safe to share between tasks: credentials and the two caches are only ever
    read/modified between awaits, which is atomic under a single event loop
    (the Go version needs a mutex for the same invariant).
    """

    def __init__(
        self,
        account_id: str = "",
        token: str = "",
        base_url: str = BASE_URL,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        verify_tls: bool = True,
        ctx_tokens_cap: int = CTX_TOKENS_CAP,
        typing_ticket_ttl: float = TYPING_TICKET_TTL_SEC,
        http_timeout: float | None = None,
    ) -> None:
        self._account_id = account_id
        self._token = token
        self._base_url = _normalize_base_url(base_url)
        self._ctx_tokens: dict[str, str] = {}
        self._typing_tickets: dict[str, tuple[str, float]] = {}
        self._ctx_tokens_cap = ctx_tokens_cap
        self._typing_ticket_ttl = typing_ticket_ttl
        # The Go client's own timeout covers the longest poll plus a margin;
        # every call site narrows it explicitly.
        default_timeout = http_timeout or (LONG_POLL_TIMEOUT_MS + 10_000) / 1000
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(default_timeout),
            transport=transport,
            verify=verify_tls,
            follow_redirects=False,
        )

    # ── lifecycle ──

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> ILinkClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ── credentials ──

    @property
    def creds(self) -> Creds:
        return Creds(self._account_id, self._token, self._base_url)

    @property
    def account_id(self) -> str:
        """The bot's own iLink id; "" while unbound."""
        return self._account_id

    def set_creds(self, account_id: str, token: str, base_url: str = "") -> None:
        """Swap credentials at runtime (used after a fresh QR bind).

        Context tokens and typing tickets are account-scoped, so an account
        change drops both caches.
        """
        if account_id != self._account_id:
            self._ctx_tokens = {}
            self._typing_tickets = {}
        self._account_id = account_id
        self._token = token
        self._base_url = _normalize_base_url(base_url)

    # ── per-peer context_token cache ──

    def context_token_for(self, peer: str) -> str:
        return self._ctx_tokens.get(peer, "")

    def set_context_token(self, peer: str, token: str) -> None:
        if not peer or not token:
            return
        if len(self._ctx_tokens) >= self._ctx_tokens_cap:
            # Soft cap: drop everything rather than grow without bound; replies
            # degrade to tokenless sends until each peer messages again.
            self._ctx_tokens = {}
        self._ctx_tokens[peer] = token

    def clear_context_token(self, peer: str) -> None:
        self._ctx_tokens.pop(peer, None)

    # ── outbound ──

    async def send_text(self, to: str, text: str) -> None:
        """Push a text message to a WeChat user.

        Long text is split into ≤`MAX_MESSAGE_LENGTH` chunks (iLink rejects
        oversized messages) with a short delay between them. Each chunk echoes
        the peer's latest context_token; on session-expired the token is
        dropped and the chunk retried once without it, so cron/push delivery
        survives an expired conversation.

        Cancellation is the caller's `asyncio` task cancellation — the sleeps
        below raise `CancelledError` exactly as the Go version's `ctx.Done()`.
        """
        if not text.strip():
            raise ValueError("ilink sendtext: text must not be empty")
        for index, chunk in enumerate(split_text_chunks(text, MAX_MESSAGE_LENGTH)):
            if index > 0:
                await asyncio.sleep(SEND_CHUNK_DELAY_SEC)
            await self._send_text_chunk(to, chunk)

    async def _send_text_chunk(self, to: str, text: str) -> None:
        """One chunk, with per-chunk retry and backoff.

        The client_id is minted once per chunk so a retry after a lost
        response is idempotent server-side (Hermes pins it per chunk too).
        """
        last_err: ILinkError | None = None
        retried_tokenless = False
        client_id = new_client_id()
        for attempt in range(SEND_RETRIES + 1):
            token, base_url = self._token, self._base_url
            context_token = self.context_token_for(to)
            payload = send_message_payload(to, text, client_id, context_token)
            try:
                body = await self._post_json(
                    base_url, EP_SEND_MESSAGE, payload, token, API_TIMEOUT_SEC
                )
            except ILinkError as exc:
                last_err = exc
            else:
                code = err_code_of(body)
                if code == 0:
                    logger.debug("ilink message sent", to=to, length=len(text))
                    return
                # No errmsg default here: Hermes treats a missing errmsg as ""
                # (rate limit), not as the stale-session "unknown error" marker.
                errmsg = _str(body.get("errmsg")) or _str(body.get("msg"))
                if is_stale_session_code(code, errmsg):
                    # Session expired — strip the context token and retry once.
                    if not retried_tokenless and context_token:
                        retried_tokenless = True
                        self.clear_context_token(to)
                        logger.warning(
                            "ilink send failed: session expired; retrying without context_token",
                            to=to,
                            code=code,
                        )
                        continue
                    logger.warning(
                        "ilink send failed: session expired, re-login via QR required",
                        to=to,
                        code=code,
                        errmsg=errmsg,
                    )
                    last_err = ILinkAPIError(
                        f"ilink sendmessage errcode={code} errmsg={errmsg}",
                        code=code,
                        errmsg=errmsg,
                        endpoint=EP_SEND_MESSAGE,
                    )
                elif code == RATE_LIMIT_ERR_CODE:
                    last_err = ILinkAPIError(
                        f"ilink sendmessage rate limited: errmsg={errmsg}",
                        code=code,
                        errmsg=errmsg,
                        endpoint=EP_SEND_MESSAGE,
                    )
                    if attempt < SEND_RETRIES:
                        wait = 3 * SEND_RETRY_DELAY_SEC
                        logger.warning("ilink send rate limited; backing off", to=to, wait=wait)
                        await asyncio.sleep(wait)
                        continue
                else:
                    # Hermes retries any API error with backoff — transient
                    # server-side rejections shouldn't drop the reply chunk.
                    last_err = ILinkAPIError(
                        f"ilink sendmessage errcode={code} errmsg={errmsg}",
                        code=code,
                        errmsg=errmsg,
                        endpoint=EP_SEND_MESSAGE,
                    )
                    logger.warning(
                        "ilink send failed with api error",
                        to=to,
                        code=code,
                        errmsg=errmsg,
                        attempt=attempt + 1,
                        of=SEND_RETRIES + 1,
                    )

            if attempt < SEND_RETRIES:
                await asyncio.sleep(SEND_RETRY_DELAY_SEC * (attempt + 1))

        # Only reachable when the last attempt failed; the Go version returns a
        # possibly-nil error here, which would report success for a chunk the
        # gateway rejected — a silent-drop bug not worth porting.
        raise last_err or ILinkError("ilink sendmessage failed without a recorded error")

    async def send_typing(self, to: str, start: bool = True) -> None:
        """Send the "对方正在输入" indicator start/stop.

        Cosmetic: callers should log a failure at debug level and carry on.
        WeChat hides the indicator after a few seconds, so a long-running
        handler must renew it (status 1) every ~5s itself.
        """
        if not to:
            raise ValueError("ilink sendtyping: empty peer")
        ticket = await self._typing_ticket_for(to)
        token, base_url = self._token, self._base_url
        await self._post_json(
            base_url,
            EP_SEND_TYPING,
            typing_payload(to, ticket, start),
            token,
            CONFIG_TIMEOUT_MS / 1000,
        )

    async def _typing_ticket_for(self, to: str) -> str:
        """The peer's typing ticket: cache hit while fresh, else getconfig.

        The context_token rides along so the ticket is minted for the live
        session rather than a stale one (Hermes `_maybe_fetch_typing_ticket`).
        """
        cached = self._typing_tickets.get(to)
        if cached and asyncio.get_running_loop().time() - cached[1] < self._typing_ticket_ttl:
            return cached[0]

        token, base_url = self._token, self._base_url
        try:
            body = await self._post_json(
                base_url,
                EP_GET_CONFIG,
                get_config_payload(to, self.context_token_for(to)),
                token,
                CONFIG_TIMEOUT_MS / 1000,
            )
        except ILinkError as exc:
            raise ILinkError(f"ilink getconfig: {exc}") from exc
        ticket = _str(body.get("typing_ticket"))
        if not ticket:
            raise ILinkError("ilink getconfig: no typing_ticket in response")
        self._typing_tickets[to] = (ticket, asyncio.get_running_loop().time())
        return ticket

    # ── inbound ──

    async def get_updates(self, sync_buf: str = "", timeout_ms: int = 0) -> GetUpdatesResult:
        """Long-poll for inbound messages.

        `sync_buf` is the opaque cursor from the previous call ("" on the first
        call). A poll timeout is not an error — the server simply had nothing
        to deliver — so the cursor is echoed back with no messages and the loop
        continues.
        """
        token, base_url = self._token, self._base_url
        if timeout_ms <= 0:
            timeout_ms = LONG_POLL_TIMEOUT_MS

        try:
            # The per-request timeout must cover the poll window plus margin.
            body = await self._post_json(
                base_url,
                EP_GET_UPDATES,
                get_updates_payload(sync_buf),
                token,
                (timeout_ms + 10_000) / 1000,
            )
        except ILinkTimeoutError:
            return GetUpdatesResult(sync_buf)

        code = err_code_of(body)
        if code != 0:
            raw_errmsg = body.get("errmsg")
            raise ILinkAPIError(
                f"ilink getupdates ret={body.get('ret')} errcode={code} errmsg={raw_errmsg}",
                code=code,
                errmsg=_str(raw_errmsg),
                ret=body.get("ret"),
                endpoint=EP_GET_UPDATES,
            )

        new_buf = _str(body.get("get_updates_buf")) or sync_buf
        suggested = _int(body.get("longpolling_timeout_ms"))
        messages = []
        raw_msgs = body.get("msgs")
        if isinstance(raw_msgs, list):
            for raw in raw_msgs:
                message = message_from_wire(raw, self._account_id)
                if message is None:
                    continue
                if message.context_token:
                    self.set_context_token(message.from_, message.context_token)
                messages.append(message)
        return GetUpdatesResult(new_buf, messages, suggested)

    async def get_config(self) -> None:
        """Lightweight GET used as a NAT keepalive between polls."""
        token, base_url = self._token, self._base_url
        await self._get_json(base_url, EP_GET_CONFIG, None, token, CONFIG_TIMEOUT_MS / 1000)

    # ── poll loop ──

    def start_poll(
        self,
        provider: CredsProvider | None,
        handler: Handler,
        send_func: SendFunc | None = None,
        cfg: PollConfig | None = None,
    ) -> asyncio.Task[None]:
        """Launch the inbound long-poll loop; returns the supervising task.

        Requires a running event loop (it calls `asyncio.create_task`). Cancel
        the returned task — or cancel the surrounding task group — to stop it.
        """
        from .poll import PollConfig, start_poll

        return start_poll(self, provider, handler, send_func, cfg or PollConfig())

    # ── HTTP helpers ──

    async def _post_json(
        self,
        base_url: str,
        endpoint: str,
        payload: dict,
        token: str,
        timeout: float,
    ) -> dict:
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": random_uin(),
            "iLink-App-Id": APP_ID,
            "iLink-App-ClientVersion": APP_CLIENT_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return await self._request(
            "POST", base_url, endpoint, headers, timeout, json_body=payload
        )

    async def _get_json(
        self,
        base_url: str,
        endpoint: str,
        params: dict | None,
        token: str,
        timeout: float,
    ) -> dict:
        headers = {
            "iLink-App-Id": APP_ID,
            "iLink-App-ClientVersion": APP_CLIENT_VERSION,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["AuthorizationType"] = "ilink_bot_token"
        return await self._request(
            "GET", base_url, endpoint, headers, timeout, params=params
        )

    async def _request(
        self,
        method: str,
        base_url: str,
        endpoint: str,
        headers: dict[str, str],
        timeout: float,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
        limit: int = RESPONSE_LIMIT,
    ) -> dict:
        url = f"{base_url}/{endpoint}"
        try:
            response = await self._http.request(
                method, url, headers=headers, json=json_body, params=params, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise ILinkTimeoutError(f"ilink /{endpoint} timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ILinkHTTPError(f"ilink /{endpoint}: {exc}") from exc

        raw = response.content[:limit]
        if response.status_code != 200:
            raise ILinkHTTPError(
                f"ilink /{endpoint} HTTP {response.status_code}: {truncate(_body_text(raw), 200)}"
            )
        try:
            body = json.loads(raw)
        except ValueError as exc:
            raise ILinkHTTPError(f"ilink decode /{endpoint}: {exc}") from exc
        if not isinstance(body, dict):
            raise ILinkHTTPError(f"ilink decode /{endpoint}: response body is not a JSON object")
        return body


def _normalize_base_url(base_url: str) -> str:
    return (base_url or BASE_URL).rstrip("/")


def _body_text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


__all__ = ["ILinkClient", "is_timeout_error", "TYPING_STATUS_START", "TYPING_STATUS_STOP"]
