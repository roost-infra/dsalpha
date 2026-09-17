"""Transport to the factor-miner MCP service.

The Factor Board does not compute factors. It posts factor code to this service —
which owns the qlib panel, the evaluator and the sandbox — and turns what comes
back into something a page can render. Two shapes make that non-obvious:

- Every tool answers over MCP JSON-RPC, and the payload arrives *as a JSON string
  inside* a ``content[].text`` envelope. The outer call is not the answer, so a
  naive ``resp["result"]`` hands back a string nobody renders.
- Heavy tools do not answer at all on the first call: they enqueue and return a
  ``job_id``, which then has to be polled on a plain REST path. The probe below
  hides both shapes behind one ``await`` so callers only see a dict.

Failure is classified, not swallowed. Three of them are for the user to fix
(auth, factor code, unconfigured service) and one is ours (dead upstream). The
classification rides on ``FactorMinerError.kind`` and ends up on the run as
``error_kind``; the reason the service gave is carried verbatim, so a caller
reads "rejected the credential" or a missing module rather than a generic 500.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from src.config.settings import (
    FACTOR_MINER_LICENSE_KEY,
    FACTOR_MINER_TIMEOUT,
    FACTOR_MINER_TOKEN,
    FACTOR_MINER_URL,
)

logger = logging.getLogger(__name__)

# How often a queued job is polled. The heavy probes run for minutes and the
# queue depth is bounded by the service, so this only has to be frequent enough
# that a finished job is not held back by our own sleep.
JOB_POLL_INTERVAL = 3.0

# A job-status read is cheap, but the miner's CPU is busy with the job itself
# while it answers — a stalled read is normal under load, not a symptom. The
# timeout is generous and a transport error is retried rather than believed.
POLL_TIMEOUT = 120.0
MAX_CONSECUTIVE_POLL_ERRORS = 5


class FactorMinerError(RuntimeError):
    """The service was reachable but would not do the work.

    ``kind`` tells the router which status to answer with; ``message`` is the
    service's own explanation, which is the part worth showing a user.
    """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class FactorMinerUnavailable(FactorMinerError):
    """No usable endpoint — unconfigured, unreachable, or wedged."""

    def __init__(self, message: str):
        super().__init__("unavailable", message)


def factor_miner_configured() -> bool:
    return bool(FACTOR_MINER_URL.strip())


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if FACTOR_MINER_LICENSE_KEY:
        headers["X-License-Key"] = FACTOR_MINER_LICENSE_KEY
    if FACTOR_MINER_TOKEN:
        headers["Authorization"] = f"Bearer {FACTOR_MINER_TOKEN}"
    return headers


def _decode_result(envelope: dict[str, Any]) -> dict[str, Any]:
    """Pull the tool's payload out of the JSON-RPC text envelope.

    A tool may answer with JSON, with prose (an error the service caught), or
    with an empty content list. Only the first is parseable, so anything else is
    preserved verbatim under ``raw`` rather than discarded — the prose is often
    the actual diagnosis.
    """
    if "error" in envelope:
        err = envelope["error"] or {}
        message = err.get("message") if isinstance(err, dict) else str(err)
        kind = "auth" if "license" in str(message).lower() else "upstream"
        raise FactorMinerError(kind, str(message or "factor-miner rejected the call"))

    result = envelope.get("result") or {}
    if result.get("isError"):
        raise FactorMinerError("upstream", _text_of(result) or "factor-miner returned an error")

    text = _text_of(result)
    if not text:
        return {}
    try:
        import json

        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {"raw": text}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _text_of(result: dict[str, Any]) -> str:
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            return str(item.get("text") or "")
    return ""


async def _rpc(client: httpx.AsyncClient, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not factor_miner_configured():
        raise FactorMinerUnavailable(
            "No factor-miner endpoint is configured. Set FACTOR_MINER_URL to the "
            "miner's address (the hub's /hub/mcp/alpha group also works)."
        )

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    try:
        # The read timeout must cover the whole call, not a pause in it. A
        # synchronous tool sends nothing until it is finished — `factor_recent_ic`
        # scans the full panel and was measured at ~283s — so a short read
        # timeout looks exactly like a dead server while it is in fact working.
        # The bound that matters is the deadline below, not this one.
        response = await client.post(
            f"{FACTOR_MINER_URL.rstrip('/')}/mcp",
            json=body,
            headers=_headers(),
            timeout=httpx.Timeout(60.0, read=FACTOR_MINER_TIMEOUT),
        )
    except (httpx.HTTPError, TimeoutError) as exc:
        # `str(exc)` is empty for several of httpx's transport errors, so the
        # class name is carried too — "ReadTimeout" and "ConnectError" are a
        # different diagnosis and a bare empty message is not one.
        raise FactorMinerUnavailable(
            f"factor-miner call to {tool} failed at {FACTOR_MINER_URL} "
            f"({type(exc).__name__}{': ' + str(exc) if str(exc) else ''})"
        ) from exc

    if response.status_code == 401:
        raise FactorMinerError("auth", "factor-miner rejected the credential (401)")
    if response.status_code >= 400:
        raise FactorMinerError(
            "upstream", f"factor-miner answered HTTP {response.status_code}: {response.text[:200]}"
        )
    try:
        envelope = response.json()
    except ValueError as exc:
        raise FactorMinerError("upstream", f"factor-miner sent a non-JSON reply: {response.text[:200]}") from exc
    return _decode_result(envelope)


async def _await_job(client: httpx.AsyncClient, job_id: str, deadline: float) -> dict[str, Any]:
    """Follow a queued job to its terminal state.

    ``asyncio.get_running_loop().time()`` is the clock rather than ``time.time``
    so a system clock change cannot stretch or collapse the deadline.

    A failed poll does not end the job. The miner serves with a thread per
    request, but a job in flight competes for CPU with the handler answering this
    poll, so a read can genuinely stall for tens of seconds without anything
    being wrong — observed against a real miner running a full-panel probe.
    Treating one slow poll as a lost job turns a working detection into a
    failure, so a transport error here is retried until the deadline; only the
    absence of the job (404) and a terminal failure are definitive.
    """
    loop = asyncio.get_running_loop()
    consecutive_errors = 0
    while True:
        if loop.time() > deadline:
            raise FactorMinerError(
                "timeout",
                f"factor-miner job {job_id} did not finish within {int(FACTOR_MINER_TIMEOUT)}s",
            )
        try:
            response = await client.get(
                f"{FACTOR_MINER_URL.rstrip('/')}/jobs/{job_id}",
                headers=_headers(),
                timeout=httpx.Timeout(POLL_TIMEOUT),
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            consecutive_errors += 1
            logger.warning(
                "factor-miner poll %s failed (%s/%s): %s: %s",
                job_id,
                consecutive_errors,
                MAX_CONSECUTIVE_POLL_ERRORS,
                type(exc).__name__,
                exc,
            )
            if consecutive_errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                raise FactorMinerUnavailable(
                    f"lost contact with factor-miner while polling job {job_id} "
                    f"({consecutive_errors} consecutive failed polls)"
                ) from exc
            await asyncio.sleep(JOB_POLL_INTERVAL)
            continue

        consecutive_errors = 0
        if response.status_code == 404:
            # A restarted service keeps no jobs; the caller re-runs.
            raise FactorMinerError("upstream", f"factor-miner no longer knows job {job_id}")
        if response.status_code >= 400:
            raise FactorMinerError("upstream", f"job poll answered HTTP {response.status_code}")

        payload = response.json()
        status = str(payload.get("status") or "")
        if status in ("done", "ok", "succeeded"):
            return _unwrap(payload.get("result"))
        if status in ("failed", "error"):
            raise FactorMinerError("upstream", _job_failure_reason(payload))
        await asyncio.sleep(JOB_POLL_INTERVAL)


def _unwrap(inner: Any) -> dict[str, Any]:
    """Decode a job's ``result``, which the service nests as a JSON string."""
    if isinstance(inner, str):
        import json

        try:
            inner = json.loads(inner)
        except ValueError:
            return {"raw": inner}
    return inner if isinstance(inner, dict) else {"raw": inner}


def _job_failure_reason(payload: dict[str, Any]) -> str:
    """The most specific reason a failed job offers.

    A worker crash is reported three times over, and only one of them is worth
    showing. The job's own ``error`` is the generic "worker exception"; the
    envelope the handler produced repeats that same string in its ``error``; the
    actual cause — a missing module, a bad window — is only in the ``traceback``.
    Verified against a live OOS failure: both error fields said "worker
    exception" while the traceback ended in ``ModuleNotFoundError: No module
    named 'jinja2'``.

    So the traceback's final line is preferred, then the envelope's message, then
    the job's own. The traceback also rides along under ``__traceback`` for a
    caller that wants to show or log the whole thing.
    """
    import json

    inner = payload.get("result")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except ValueError:
            inner = None

    if isinstance(inner, dict):
        reason = _exception_line(inner.get("traceback"))
        if reason:
            return reason
        if inner.get("error"):
            return str(inner["error"])
    return str(payload.get("error") or "factor-miner job failed")


def _exception_line(traceback_text: Any) -> str | None:
    """The exception a Python traceback ends with.

    The last non-empty line is the exception itself; the lines above it are
    frames that mean nothing to whoever reads the verdict card. Falls back to the
    last line of a traceback that is not shaped like one Python prints.
    """
    if not isinstance(traceback_text, str) or not traceback_text.strip():
        return None
    lines = [line.strip() for line in traceback_text.strip().splitlines() if line.strip()]
    if not lines:
        return None
    return lines[-1]


async def call_tool(tool: str, arguments: dict[str, Any], *, deadline: float | None = None) -> dict[str, Any]:
    """Run one factor-miner tool and return its decoded payload.

    A tool that enqueues is followed to completion here, so a caller never sees a
    ``job_id``; ``deadline`` is a loop-clock instant bounding the whole call.
    """
    loop = asyncio.get_running_loop()
    if deadline is None:
        deadline = loop.time() + FACTOR_MINER_TIMEOUT

    async with httpx.AsyncClient() as client:
        payload = await _rpc(client, tool, arguments)
        job_id = payload.get("job_id")
        if job_id:
            logger.info("factor-miner queued %s as %s", tool, job_id)
            return await _await_job(client, str(job_id), deadline)
        return payload


async def health() -> dict[str, Any]:
    """Report reachability without spending a probe slot."""
    if not factor_miner_configured():
        return {"configured": False, "reachable": False, "url": ""}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{FACTOR_MINER_URL.rstrip('/')}/health", timeout=httpx.Timeout(10.0)
            )
        reachable = response.status_code == 200
        body: dict[str, Any] = response.json() if reachable else {}
        return {
            "configured": True,
            "reachable": reachable,
            "url": FACTOR_MINER_URL,
            "version": body.get("version"),
            "auth": body.get("auth"),
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"configured": True, "reachable": False, "url": FACTOR_MINER_URL, "error": str(exc)}
