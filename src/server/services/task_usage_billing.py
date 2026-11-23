"""Charge settled subagent/task usage to the console.

A task run records its own ``conversation_usages`` row but has no credit-gate
lease of its own, so the parent turn's release does not include it. Charge each
task row directly after it commits, using the console's idempotent direct-charge
endpoint (``ref`` is the usage row id, so a retry is a replay).
"""

import json
import logging
import math

from src.config.settings import AUTH_SERVICE_URL
from src.server.dependencies import usage_limits

logger = logging.getLogger(__name__)

_CHARGE_PATH = "/internal/v1/usage/charge"
_RESOLVE_PATH = "/internal/v1/orgs/resolve-user"
_org_cache: dict[str, str] = {}


def _url(path: str) -> str:
    return f"{AUTH_SERVICE_URL.rstrip('/')}{path}"


async def _org_for_user(user_id: str, client) -> str | None:
    cached = _org_cache.get(user_id)
    if cached:
        return cached
    body = {"user_id": user_id}
    raw = json.dumps(body, separators=(",", ":")).encode()
    try:
        resp = await client.post(
            _url(_RESOLVE_PATH),
            content=raw,
            headers=usage_limits.signed_service_headers("POST", _RESOLVE_PATH, raw),
        )
        if resp.status_code != 200:
            logger.warning(
                "task billing: resolve org %s -> %s", user_id, resp.status_code
            )
            return None
        org = (resp.json() or {}).get("id")
        if not isinstance(org, str) or not org:
            return None
        _org_cache[user_id] = org
        return org
    except Exception as e:
        logger.warning("task billing: resolve org %s failed: %s", user_id, e)
        return None


async def charge_task_usage(user_id: str, ref: str, credits: float) -> bool:
    """Charge one task usage row. False means it was not accepted; caller logs."""
    amount = int(math.ceil(max(0.0, credits)))
    if amount <= 0 or not AUTH_SERVICE_URL or usage_limits.service_token_missing():
        return True
    client = await usage_limits.get_http_client()
    org = await _org_for_user(user_id, client)
    if not org:
        return False
    body = {"org_id": org, "product": "dsalpha", "ref": ref, "credits": amount}
    raw = json.dumps(body, separators=(",", ":")).encode()
    try:
        resp = await client.post(
            _url(_CHARGE_PATH),
            content=raw,
            headers=usage_limits.signed_service_headers("POST", _CHARGE_PATH, raw),
        )
    except Exception as e:
        logger.warning("task billing: charge %s failed: %s", ref, e)
        return False
    if resp.status_code == 200:
        return True
    logger.warning(
        "task billing: charge %s -> %s %s", ref, resp.status_code, resp.text[:200]
    )
    return False
