"""Application assembly: lifespan, config, schema bootstrap and health."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import ingest
from .admin_api import router as admin_api_router
from .admin_ui import router as admin_ui_router
from .api import router as langalpha_router
from .config import load_settings
from .db import close_pool, fetch_one, init_pool, run_sql_script


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    app.state.settings = settings
    await init_pool(settings.database_url)
    if settings.auto_migrate:
        # The schema is idempotent, so applying it on boot keeps a small
        # deployment from needing a separate migration step.
        await run_sql_script(Path(__file__).with_name("schema.sql"))

    ingest_task: asyncio.Task | None = None
    if settings.ingest_enabled:
        ingest_task = asyncio.create_task(ingest.run_forever(settings))
        app.state.ingest_task = ingest_task
    yield
    if ingest_task is not None:
        ingest_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ingest_task
    await close_pool()


app = FastAPI(title="dsalpha quota service", version="0.1.0", lifespan=lifespan)
app.include_router(langalpha_router)
app.include_router(admin_api_router)
app.include_router(admin_ui_router)


@app.get("/healthz")
async def healthz():
    await fetch_one("SELECT 1 AS ok")
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """A deliberately small exposition: ingestion health is what pages."""
    snapshot = ingest.stats.snapshot()
    lines = [
        "# TYPE quota_ingest_ledger_entries_total counter",
        f"quota_ingest_ledger_entries_total {snapshot['ledger_entries']}",
        "# TYPE quota_ingest_errors_total counter",
        f"quota_ingest_errors_total {snapshot['errors']}",
        "# TYPE quota_ingest_last_success_seconds gauge",
        f"quota_ingest_last_success_seconds {snapshot['last_success']}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n")


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    # A stack trace must never reach a caller; dsalpha only logs the status.
    return JSONResponse(status_code=500, content={"detail": "internal error"})


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "quota_service.main:app",
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
