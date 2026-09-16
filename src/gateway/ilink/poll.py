"""Inbound long-poll loop for the iLink bot.

The loop is the reason this package is async: it holds a 35s long-poll open
almost continuously, pings `getconfig` as a NAT keepalive in between, and
re-reads the credential provider every 10s so a QR bind (or unbind) takes
effect without a restart.

Port of athena's `internal/gateway/ilink/poll.go`. Cancellation replaces Go's
`ctx`: cancel the task returned by `start_poll` to stop the loop.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Protocol, runtime_checkable

import structlog

from .models import (
    BACKOFF_DELAY_SEC,
    CRED_CHECK_INTERVAL_SEC,
    HANDLER_ERROR_REPLY,
    KEEPALIVE_INTERVAL_SEC,
    LONG_POLL_TIMEOUT_MS,
    MAX_CONSECUTIVE_FAILURES,
    POLL_RESTART_BACKOFF_SEC,
    RATE_LIMIT_ERR_CODE,
    RETRY_DELAY_SEC,
    SESSION_EXPIRED_ERR_CODE,
    SESSION_EXPIRED_PAUSE_SEC,
    Creds,
    InboundMessage,
    is_stale_session_code,
)

if TYPE_CHECKING:
    from .client import ILinkClient

logger = structlog.get_logger(__name__)


@runtime_checkable
class Handler(Protocol):
    """Processes one inbound WeChat message and returns the reply text.

    Empty/None reply = nothing is sent. A handler may be sync or async; it is
    invoked sequentially, so a slow handler blocks the poll loop and handlers
    should keep their work bounded (same contract as the Go version).
    """

    def __call__(self, from_: str, text: str) -> Awaitable[str | None] | str | None: ...


@runtime_checkable
class SendFunc(Protocol):
    """Sends a reply back to the user; raises on failure."""

    def __call__(self, to: str, text: str) -> Awaitable[None]: ...


# The Go provider returns (accountID, token, baseURL, ok). A Python caller
# naturally has a Creds object, so both spellings are accepted.
CredsSource = Creds | tuple[str, str, str, bool] | tuple[str, str, str] | None


@runtime_checkable
class CredsProvider(Protocol):
    """Yields the current bot credentials.

    Returning `None` means "no valid credentials" — the poll loop parks and
    stays off the network until a fresh QR bind appears.
    """

    def __call__(self) -> CredsSource: ...


@dataclass(frozen=True, slots=True)
class PollConfig:
    """Poll loop tuning. Zero values use the production defaults.

    `session_expired_pause_sec` has no Go knob (it is a const there); it is
    exposed so the -14 pause path is testable without a 10-minute wait.
    """

    long_poll_timeout_ms: int = 0
    keepalive_sec: float = 0.0
    cred_check_sec: float = 0.0
    session_expired_pause_sec: float = 0.0

    def resolved(self) -> PollConfig:
        return PollConfig(
            long_poll_timeout_ms=self.long_poll_timeout_ms or LONG_POLL_TIMEOUT_MS,
            keepalive_sec=self.keepalive_sec or KEEPALIVE_INTERVAL_SEC,
            cred_check_sec=self.cred_check_sec or CRED_CHECK_INTERVAL_SEC,
            session_expired_pause_sec=self.session_expired_pause_sec
            or SESSION_EXPIRED_PAUSE_SEC,
        )


class Deduper:
    """Bounded message-id memory so a replayed long-poll response is handled once."""

    SEEN_CAP = 500
    TTL_SEC = 600.0

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def is_seen(self, message_id: str) -> bool:
        return bool(message_id) and message_id in self._seen

    def add(self, message_id: str) -> None:
        if not message_id:
            return
        self._seen[message_id] = time.monotonic()
        if len(self._seen) > self.SEEN_CAP:
            cutoff = time.monotonic() - self.TTL_SEC
            for key in [k for k, seen_at in self._seen.items() if seen_at < cutoff]:
                del self._seen[key]

    def reset(self) -> None:
        self._seen = {}

    def __len__(self) -> int:
        return len(self._seen)


def normalize_creds(value: CredsSource) -> Creds | None:
    """Coerce a provider result into `Creds`, or None when unbound.

    Partial credentials (an account without a token, say) are treated as
    unbound: polling with them would only produce 401s.
    """
    if value is None:
        return None
    if isinstance(value, Creds):
        creds = value
    elif isinstance(value, tuple) and len(value) == 4:
        account_id, token, base_url, ok = value
        if not ok:
            return None
        creds = Creds(str(account_id), str(token), str(base_url or ""))
    elif isinstance(value, tuple) and len(value) == 3:
        account_id, token, base_url = value
        creds = Creds(str(account_id), str(token), str(base_url or ""))
    else:
        raise TypeError(f"ilink creds provider returned {value!r}; expected Creds, tuple or None")
    if not creds.account_id or not creds.token:
        return None
    return creds


def is_session_expired(exc: BaseException) -> bool:
    """The -14 session expiry, plus the stale-session variant Hermes detects.

    `ILinkAPIError` carries the code, so that path needs no text matching; a
    foreign exception falls back to the Go implementation's substring test
    (`errcode=-2` + `errmsg=unknown error` on the getupdates path).
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return is_stale_session_code(code, str(getattr(exc, "errmsg", "") or ""))
    message = str(exc)
    return f"errcode={SESSION_EXPIRED_ERR_CODE}" in message or (
        f"errcode={RATE_LIMIT_ERR_CODE}" in message and "errmsg=unknown error" in message
    )


class PollLoop:
    """One run of the inbound loop. Prefer `start_poll`, which supervises it."""

    def __init__(
        self,
        client: ILinkClient,
        provider: CredsProvider | None,
        handler: Handler,
        send_func: SendFunc | None = None,
        cfg: PollConfig | None = None,
    ) -> None:
        self._client = client
        self._provider = provider
        self._handler = handler
        self._send_func = send_func
        self._cfg = (cfg or PollConfig()).resolved()

        self._sync_buf = ""
        self._dedup = Deduper()
        self._cred_fp = ""  # last applied credential fingerprint; never logged
        self._idle = False  # parked until a QR bind provides credentials

    async def run(self) -> None:
        logger.info("ilink poll loop started")

        consecutive_failures = 0
        timeout_ms = self._cfg.long_poll_timeout_ms
        last_keepalive: float | None = None
        last_cred_check: float | None = None

        while True:
            # 1. Re-read credentials periodically so a QR bind applies live —
            #    and a QR unbind (or booting unbound) parks the loop instead of
            #    hammering the API with stale/no credentials.
            if self._provider is not None and self._due(last_cred_check, self._cfg.cred_check_sec):
                last_cred_check = self._now()
                creds = normalize_creds(self._provider())
                if creds is not None:
                    fingerprint = f"{creds.account_id}|{creds.token}"
                    if fingerprint != self._cred_fp:
                        logger.info("ilink credentials updated", account=creds.account_id)
                        self._client.set_creds(creds.account_id, creds.token, creds.base_url)
                        self._cred_fp = fingerprint
                        # New session: drop in-memory cursor/dedup, reset backoff.
                        self._sync_buf = ""
                        self._dedup.reset()
                        consecutive_failures = 0
                        if self._idle:
                            self._idle = False
                            logger.info("ilink poll loop resumed")
                elif not self._idle:
                    # Bound → unbound transition: stop polling entirely until a
                    # fresh QR bind lands (provider turns ok again).
                    self._idle = True
                    self._cred_fp = ""
                    consecutive_failures = 0
                    logger.info("ilink credentials absent; poll loop idling until a QR bind")

            if self._idle:
                await asyncio.sleep(self._cfg.cred_check_sec)
                continue

            # 2. NAT keepalive between polls.
            if self._due(last_keepalive, self._cfg.keepalive_sec):
                last_keepalive = self._now()
                try:
                    await self._client.get_config()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug("ilink keepalive failed (ignored)", error=str(exc))

            # 3. Long-poll for messages.
            try:
                result = await self._client.get_updates(self._sync_buf, timeout_ms)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consecutive_failures += 1
                if is_session_expired(exc):
                    logger.warning("ilink session expired; pausing — re-login via QR required")
                    # Pause for the full window, but wake up early if credentials
                    # change (a fresh QR bind lands) so the loop resumes promptly.
                    await self._wait_creds_change(self._cfg.session_expired_pause_sec)
                    # Pause elapsed without a rebind — keep looping (matches
                    # Hermes: repeated pauses, never a permanent exit).
                    consecutive_failures = 0
                    continue
                delay = RETRY_DELAY_SEC
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    delay = BACKOFF_DELAY_SEC
                    consecutive_failures = 0
                logger.warning("ilink poll error", error=str(exc), attempt=consecutive_failures)
                await asyncio.sleep(delay)
                continue

            consecutive_failures = 0
            if result.sync_buf:
                self._sync_buf = result.sync_buf
            if result.suggested_timeout_ms > 0:
                timeout_ms = result.suggested_timeout_ms

            # 4. Handle each message, replying inline.
            for message in result.messages:
                if self._dedup.is_seen(message.message_id):
                    logger.debug("ilink duplicate message skipped", id=message.message_id)
                    continue
                self._dedup.add(message.message_id)
                await self._handle_message(message)

            # 5. Cooperative yield. The loop is only paced by the *server*
            #    holding the long poll open; against an instantly-answering
            #    gateway (or a mocked transport in tests) nothing inside an
            #    iteration awaits, and asyncio — unlike Go's scheduler — cannot
            #    preempt a busy coroutine, so every other task on this event
            #    loop would starve. sleep(0) hands control back without adding
            #    latency.
            await asyncio.sleep(0)

    async def _handle_message(self, message: InboundMessage) -> None:
        if not message.text:
            logger.debug(
                "ilink non-text message ignored", from_=message.from_, msg_type=message.msg_type
            )
            return
        logger.info("ilink inbound", from_=message.from_, length=len(message.text))

        try:
            reply = self._handler(message.from_, message.text)
            if inspect.isawaitable(reply):
                reply = await reply
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ilink handler error", from_=message.from_)
            reply = HANDLER_ERROR_REPLY

        if not reply:
            return
        if self._send_func is None:
            logger.warning("ilink reply dropped (no sendFunc)", from_=message.from_)
            return
        try:
            await self._send_func(message.from_, reply)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("ilink reply send failed", from_=message.from_, error=str(exc))

    async def _wait_creds_change(self, max_wait: float) -> bool:
        """Block until the credential fingerprint changes or `max_wait` elapses.

        Used after a -14 pause so a fresh QR bind resumes the loop immediately
        instead of waiting out the whole window.
        """
        if self._provider is None:
            await asyncio.sleep(max_wait)
            return False
        deadline = self._now() + max_wait
        while self._now() < deadline:
            await asyncio.sleep(self._cfg.cred_check_sec)
            creds = normalize_creds(self._provider())
            if creds is not None and f"{creds.account_id}|{creds.token}" != self._cred_fp:
                logger.info("ilink credentials changed during pause; resuming poll")
                return True
        return False

    def _due(self, last: float | None, interval: float) -> bool:
        return last is None or self._now() - last >= interval

    @staticmethod
    def _now() -> float:
        return asyncio.get_running_loop().time()


def start_poll(
    client: ILinkClient,
    provider: CredsProvider | None,
    handler: Handler,
    send_func: SendFunc | None = None,
    cfg: PollConfig | None = None,
) -> asyncio.Task[None]:
    """Launch the inbound long-poll loop; returns the supervising task.

    A crash inside the loop (a handler blowing up in third-party code, say) is
    logged and the loop restarts after a 5s backoff rather than either dying
    permanently or spinning on a deterministic failure. Cancel the task to stop
    it. Must be called from a running event loop.
    """
    loop = PollLoop(client, provider, handler, send_func, cfg)
    return asyncio.create_task(_supervise(loop), name="ilink-poll")


async def _supervise(loop: PollLoop) -> None:
    while True:
        try:
            await loop.run()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "ilink poll loop crashed; restarting after backoff",
                backoff_sec=POLL_RESTART_BACKOFF_SEC,
            )
        await asyncio.sleep(POLL_RESTART_BACKOFF_SEC)


__all__ = [
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
]
