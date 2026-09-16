"""QR bind flow for the iLink bot (no credentials required — minted on the fly).

Two steps, both unauthenticated: `fetch_qr` asks for a scan-login code, then
the caller polls `poll_qr` with the returned `qr_value` until the status turns
`confirmed` (carrying the bot credentials) or `expired`. A `scaned_but_redirect`
result means Tencent moved the status endpoint to another WeChat host, and the
next poll must be sent to `QRResult.redirect_base` instead.

Port of athena's `internal/gateway/ilink/qr.go`.
"""

from __future__ import annotations

import json
from typing import Callable
from urllib.parse import urlparse

import httpx
import structlog

from .models import (
    APP_CLIENT_VERSION,
    APP_ID,
    BASE_URL,
    EP_GET_BOT_QR,
    EP_GET_QR_STATUS,
    QR_RESPONSE_LIMIT,
    ILinkHTTPError,
    ILinkTimeoutError,
    QRResult,
    truncate,
)

logger = structlog.get_logger(__name__)

QR_TIMEOUT_SEC = 35.0
QR_STATUS_TIMEOUT_SEC = 15.0

# The iLink app identifies itself with these two headers on every call, even
# the unauthenticated QR ones.
_APP_HEADERS = {
    "iLink-App-Id": APP_ID,
    "iLink-App-ClientVersion": APP_CLIENT_VERSION,
}


def redirect_base_of(host: str) -> str:
    """Turn a `redirect_host` into a full https base URL."""
    host = host.strip()
    return f"https://{host}" if host else ""


def assert_weixin_host(base_url: str) -> None:
    """Reject poll base URLs that are not https Tencent WeChat hosts.

    The base is client-supplied (a `redirect_host` echoed back to the caller),
    so an unguarded fetch here would be an SSRF vector against internal
    services. `ilinkai.weixin.qq.com` or any `*.weixin.qq.com` is allowed.
    """
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or (
        host != "ilinkai.weixin.qq.com" and not host.endswith(".weixin.qq.com")
    ):
        raise ILinkHTTPError(
            f'ilink qr base url host "{host}" is not an allowed WeChat host'
        )


# Swappable so tests can point the status poll at a local server (the Go
# package has the same hook); production always runs the guard above.
qr_base_guard: Callable[[str], None] = assert_weixin_host


async def fetch_qr(
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = QR_TIMEOUT_SEC,
) -> tuple[str, str]:
    """Request a fresh WeChat scan-login QR code.

    Returns `(qr_value, qr_image_url)`: `qr_value` is the opaque token used for
    status polling, `qr_image_url` is the liteapp link the user actually opens
    in WeChat to scan.
    """
    body = await _qr_get(
        EP_GET_BOT_QR,
        {"bot_type": "3"},
        label="get_bot_qrcode",
        client=client,
        timeout=timeout,
    )
    qr_value = body.get("qrcode")
    if not isinstance(qr_value, str) or not qr_value:
        raise ILinkHTTPError("ilink get_bot_qrcode: empty qrcode")
    qr_image_url = body.get("qrcode_img_content")
    qr_image_url = qr_image_url if isinstance(qr_image_url, str) else ""
    logger.info("ilink QR fetched", has_image=bool(qr_image_url))
    return qr_value, qr_image_url


async def poll_qr(
    qr_value: str,
    base_url: str = "",
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = QR_STATUS_TIMEOUT_SEC,
    guard: Callable[[str], None] | None = None,
) -> QRResult:
    """Poll the scan status of `qr_value` against `base_url` (default host when "").

    Pass the previous result's `redirect_base` after a `scaned_but_redirect`.
    """
    target = (base_url or BASE_URL).rstrip("/")
    (guard or qr_base_guard)(target)

    body = await _qr_get(
        EP_GET_QR_STATUS,
        {"qrcode": qr_value},
        label="get_qrcode_status",
        client=client,
        timeout=timeout,
        base_url=target,
    )
    status = body.get("status")
    result = QRResult(
        status=status if isinstance(status, str) and status else "wait",
        account_id=_str(body.get("ilink_bot_id")),
        token=_str(body.get("bot_token")),
        base_url=_str(body.get("baseurl")) or BASE_URL,
        user_id=_str(body.get("ilink_user_id")),
        redirect_base=redirect_base_of(_str(body.get("redirect_host"))),
    )
    return result


async def _qr_get(
    endpoint: str,
    params: dict[str, str],
    *,
    label: str,
    client: httpx.AsyncClient | None,
    timeout: float,
    base_url: str = BASE_URL,
) -> dict:
    if client is None:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as owned:
            return await _qr_get(
                endpoint,
                params,
                label=label,
                client=owned,
                timeout=timeout,
                base_url=base_url,
            )

    url = f"{base_url.rstrip('/')}/{endpoint}"
    try:
        response = await client.get(url, headers=_APP_HEADERS, params=params, timeout=timeout)
    except httpx.TimeoutException as exc:
        # A QR status poll is a long poll: a client-side timeout means "nothing
        # yet", so callers need to tell it apart from a real failure.
        raise ILinkTimeoutError(f"ilink {label}: timeout: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ILinkHTTPError(f"ilink {label}: {exc}") from exc

    raw = response.content[:QR_RESPONSE_LIMIT]
    text = raw.decode("utf-8", errors="replace")
    if response.status_code != 200:
        raise ILinkHTTPError(
            f"ilink {label} HTTP {response.status_code}: {truncate(text, 200)}"
        )
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise ILinkHTTPError(f"ilink {label} decode: {exc}") from exc
    if not isinstance(body, dict):
        raise ILinkHTTPError(f"ilink {label} decode: response body is not a JSON object")
    return body


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


__all__ = [
    "QR_STATUS_TIMEOUT_SEC",
    "QR_TIMEOUT_SEC",
    "assert_weixin_host",
    "fetch_qr",
    "poll_qr",
    "qr_base_guard",
    "redirect_base_of",
]
