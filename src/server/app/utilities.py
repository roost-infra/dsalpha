"""
Utility endpoints for TTS, podcast, RAG, config, health checks, and WebSocket.

This module handles miscellaneous endpoints:
- Text-to-speech conversion
- Podcast generation
- RAG configuration and resources
- Server configuration
- WebSocket chat
- Health checks
- Custom metrics
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
INTERNAL_SERVER_ERROR_DETAIL = "Internal Server Error"

# Create router (health checks are unversioned at /health)
health_router = APIRouter(tags=["Health"])
_PROBE_TIMEOUT_SECONDS = 2.0


def _read_source_sha() -> str | None:
    stamp = Path(__file__).resolve().parents[2] / ".release-sha"
    try:
        sha = stamp.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    return sha if re.fullmatch(r"[a-f0-9]{40}", sha) else None


# Keep the version with the running process even if its source is swapped.
_SOURCE_SHA = _read_source_sha()


@health_router.get("/health/live")
async def liveness():
    """Answer only for the serving process."""
    return {"status": "alive"}


async def _dependency_status(check: Callable[[], Awaitable[str]]) -> str:
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            return await check()
    except TimeoutError:
        return "timeout"
    except Exception:
        return "unavailable"


@health_router.get("/health/ready")
async def readiness():
    """Check core dependencies in parallel and report optional tool loss."""
    from ptc_agent.core.mcp_registry import get_global_registry
    from src.observability.langsmith_run import build_sha
    from src.server.app.setup import checkpointer
    from src.server.database.pool import check_database_connection
    from src.server.utils.checkpointer import get_checkpointer_health
    from src.utils.cache.redis_cache import get_cache_client

    async def database() -> str:
        await check_database_connection()
        return "healthy"

    async def checkpoint() -> str:
        if checkpointer is None:
            return "unavailable"
        stats = await get_checkpointer_health(checkpointer)
        if stats.get("status") == "not_configured" and not hasattr(checkpointer, "conn"):
            return "not_applicable"
        return "healthy" if stats.get("status") == "healthy" else "unavailable"

    async def redis() -> str:
        return "healthy" if await get_cache_client().health_check() else "unavailable"

    checks = {"database": database, "checkpointer": checkpoint, "redis": redis}
    states = await asyncio.gather(*(_dependency_status(check) for check in checks.values()))
    dependencies = dict(zip(checks, states, strict=True))
    ready = all(state in {"healthy", "not_applicable"} for state in states)
    registry = get_global_registry()
    optional = {"mcp": "degraded" if registry and registry.failed_builtin_remote else "healthy"}
    payload = {
        "status": "ready" if ready else "unready",
        "dependencies": dependencies,
        "optional": optional,
        "source_sha": _SOURCE_SHA,
        "build_sha": build_sha(),
    }
    return JSONResponse(payload, status_code=200 if ready else 503)

@health_router.get("/health")
async def health_check():
    """Health check endpoint with checkpointer pool stats.

    A built-in remote MCP server that failed boot discovery makes this a 503,
    not only a body field: readiness probes read the status code, and this
    process serves without that server's tools until its background reconnect
    gets through. Each worker discovers and reconnects on its own, so the
    answer is this worker's.
    """
    from ptc_agent.core.mcp_registry import get_global_registry
    from src.server.app.setup import checkpointer
    from src.server.utils.checkpointer import get_checkpointer_health

    result = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0",
        "service": "ptc-agent",
    }

    # Include checkpointer pool health if configured
    try:
        checkpointer_health = await get_checkpointer_health(checkpointer)
        result["checkpointer"] = checkpointer_health
        if checkpointer_health.get("status") == "unhealthy":
            result["status"] = "degraded"
    except Exception as e:
        result["checkpointer"] = {"status": "error", "error": str(e)}
        result["status"] = "degraded"

    registry = get_global_registry()
    if registry is not None and registry.failed_builtin_remote:
        result["mcp"] = {
            "status": "degraded",
            "failed_servers": sorted(registry.failed_builtin_remote),
        }
        result["status"] = "unhealthy"
        return JSONResponse(result, status_code=503)

    return result
