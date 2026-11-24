"""Charge settled subagent/task usage to the console.

A task run records its own ``conversation_usages`` row but has no credit-gate
lease of its own. The parent turn's release does not include it, so the task
charges the console using a usage-derived idempotency reference.
"""

import json
import logging
import math

from src.config.settings import AUTH_SERVICE_URL
from src.server.database.runs import outbox
from src.server.database.runs.hook_jobs import TASK_USAGE_CHARGE_HOOK, HookJob
from src.server.dependencies import usage_limits

logger = logging.getLogger(__name__)

_CHARGE_PATH = "/internal/v1/usage/charge"
_RESOLVE_PATH = "/internal/v1/orgs/resolve-user"
_direct_org_cache: dict[str, str] = {}


def _url(path: str) -> str:
    return f"{AUTH_SERVICE_URL.rstrip('/')}{path}"


async def _org_for_user(user_id: str, client) -> str | None:
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
        return org
    except Exception as e:
        logger.warning("task billing: resolve org %s failed: %s", user_id, e)
        return None


async def _charge_org_usage(client, org_id: str, ref: str, credits: float) -> bool:
    """Deliver one charge with the durable reference and billing destination."""
    amount = int(math.ceil(max(0.0, credits)))
    body = {"org_id": org_id, "product": "dsalpha", "ref": ref, "credits": amount}
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


async def charge_task_usage_direct(user_id: str, ref: str, credits: float) -> None:
    """Keep direct charging available while workers are being upgraded."""
    if usage_limits.service_token_missing():
        return
    client = await usage_limits.get_http_client()
    org_id = _direct_org_cache.get(user_id) or await _org_for_user(user_id, client)
    if org_id:
        _direct_org_cache[user_id] = org_id
        if await _charge_org_usage(client, org_id, ref, credits):
            return
    logger.warning("Task usage charge was not accepted, ref=%s", ref)


def task_charge_job(usage_id: str, user_id: str, credits: float) -> HookJob:
    return HookJob(
        hook_type=TASK_USAGE_CHARGE_HOOK,
        idempotency_key=f"task-usage:{usage_id}",
        payload={"user_id": user_id, "credits": credits},
    )


async def execute_task_charge(job: dict) -> None:
    payload = job["payload"]
    ref = job["idempotency_key"]
    if not usage_limits.platform_gating_active() or usage_limits.service_token_missing():
        raise RuntimeError(f"Task usage charge service is unavailable, ref={ref}")
    client = await usage_limits.get_http_client()
    org_id = payload.get("org_id")
    if not org_id:
        org_id = await _org_for_user(payload["user_id"], client)
        if not org_id or not await outbox.bind_task_charge_org(
            job["hook_outbox_id"], attempts=job["attempts"], org_id=org_id
        ):
            raise RuntimeError(f"Task usage charge destination was not saved, ref={ref}")
    if not await _charge_org_usage(client, org_id, ref, payload["credits"]):
        raise RuntimeError(f"Task usage charge was not accepted, ref={ref}")


def register_outbox_executors() -> None:
    from src.server.services.hook_outbox import register_hook_executor

    register_hook_executor(TASK_USAGE_CHARGE_HOOK, execute_task_charge)
