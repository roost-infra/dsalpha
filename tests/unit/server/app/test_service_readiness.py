from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ptc_agent.core import mcp_registry
from src.observability import langsmith_run
from src.server.app import setup, utilities
from src.server.database import pool
from src.server.utils import checkpointer
from src.utils.cache import redis_cache


@pytest.fixture
def probes(monkeypatch):
    database = AsyncMock()
    checkpoint = AsyncMock(return_value={"status": "healthy"})
    redis = AsyncMock(return_value=True)
    monkeypatch.setattr(pool, "check_database_connection", database)
    monkeypatch.setattr(checkpointer, "get_checkpointer_health", checkpoint)
    monkeypatch.setattr(redis_cache, "get_cache_client", lambda: SimpleNamespace(health_check=redis))
    monkeypatch.setattr(setup, "checkpointer", SimpleNamespace(conn=object()))
    monkeypatch.setattr(mcp_registry, "get_global_registry", lambda: None)
    monkeypatch.setattr(utilities, "_SOURCE_SHA", "1" * 40)
    monkeypatch.setattr(langsmith_run, "build_sha", lambda: "2" * 40)
    app = FastAPI()
    app.include_router(utilities.health_router)
    with TestClient(app) as client:
        yield client, database, checkpoint, redis


def test_liveness_never_checks_dependencies(probes):
    client, database, checkpoint, redis = probes
    database.side_effect = RuntimeError("database is down")
    assert client.get("/health/live").json() == {"status": "alive"}
    for check in (database, checkpoint, redis):
        check.assert_not_awaited()


def test_readiness_reports_versions_and_optional_degradation(probes, monkeypatch):
    client, _, _, _ = probes
    monkeypatch.setattr(
        mcp_registry, "get_global_registry",
        lambda: SimpleNamespace(failed_builtin_remote={"optional": "internal error"}),
    )
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"database": "healthy", "checkpointer": "healthy", "redis": "healthy"},
        "optional": {"mcp": "degraded"},
        "source_sha": "1" * 40,
        "build_sha": "2" * 40,
    }
    assert client.get("/health").status_code == 503


@pytest.mark.parametrize("dependency", ["database", "checkpointer", "redis"])
def test_readiness_fails_closed_and_hides_dependency_errors(probes, dependency):
    client, *checks = probes
    by_name = dict(zip(("database", "checkpointer", "redis"), checks, strict=True))
    by_name[dependency].side_effect = RuntimeError("internal diagnostic")
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"][dependency] == "unavailable"
    assert "internal diagnostic" not in response.text


def test_readiness_distinguishes_a_timed_out_dependency(probes):
    client, _, _, redis = probes
    redis.side_effect = TimeoutError
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["redis"] == "timeout"
