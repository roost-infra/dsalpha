"""Factor Board API — the factor library and one-click detection.

Two halves, both user-scoped like every other page-backed router here:

**Library** (durable): the factors a user keeps, with the hypothesis behind each
one and the metrics its last evaluation produced.

- ``GET    /api/v1/factors/library`` list, filtered by status/source/text
- ``POST   /api/v1/factors/library`` save (upsert by name; hypothesis required)
- ``GET    /api/v1/factors/library/{id}`` one factor in full
- ``DELETE /api/v1/factors/library/{id}``
- ``POST   /api/v1/factors/library/{id}/status`` promote / reject / reopen
- ``POST   /api/v1/factors/library/{id}/evaluate`` start a professional evaluation

**Detection** (process-local): run a script once and get a verdict. ``POST``
starts it and the page polls, because the contract check returns in seconds while
the IC probes scan the panel for minutes.

Both long-running paths are submit-and-poll for the same reason, but they keep
state in different places on purpose: a detection is a disposable probe whose
ledger is process-local and expires, while an evaluation belongs to a stored
factor and its state lives in that factor's row — the board can be reloaded, or
served by another worker, and still read the truth.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.server.models.factor import (
    DetectionListResponse,
    DetectionRequest,
    DetectionRunResponse,
    DetectionStage,
    FactorEvaluateRequest,
    FactorLibraryItem,
    FactorLibraryListResponse,
    FactorLibrarySummary,
    FactorMinerHealthResponse,
    FactorSaveRequest,
    FactorStatusRequest,
    FactorTemplate,
    FactorTemplatesResponse,
)
from src.server.services import factor_library as library
from src.server.services import factor_miner
from src.server.services.factor_detection import (
    FACTOR_TEMPLATES,
    DetectionRun,
    get_run,
    recent_runs,
    start_detection,
)
from src.server.services.factor_library import EvaluationInFlight
from src.server.utils.api import CurrentUserId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/factors", tags=["Factor Board"])

# Real column names only: the response's ``ic``/``ir``/``t_stat``/``monotonicity``
# are *lifted out of* ``metrics`` (the board sorts a table on them without digging
# into a nested object per row), so they are not columns and must not be read as
# if they were.
_ROW_FIELDS = (
    "name",
    "hypothesis",
    "description",
    "source",
    "status",
    "code_hash",
    "last_evaluated_at",
    "promoted_at",
    "created_at",
    "updated_at",
)


def _summary_fields(row: dict) -> dict:
    """The fields both shapes share, with the two coercions they both need.

    ``factor_id`` arrives as a UUID object and is stringified for the wire;
    ``monotonicity`` is absent on a row that has never been evaluated, and the
    board expects a dict to render, not a null to branch on.
    """
    metrics = row.get("metrics") or {}
    return {
        **{key: row.get(key) for key in _ROW_FIELDS},
        "factor_id": str(row.get("factor_id") or ""),
        "ic": metrics.get("ic"),
        "ir": metrics.get("ir"),
        "t_stat": metrics.get("t_stat"),
        "ic_half_life_days": metrics.get("ic_half_life_days"),
        "monotonicity": metrics.get("monotonicity") or {},
        "evaluation": library.evaluation_state(metrics),
    }


def _serialize_library_summary(row: dict) -> FactorLibrarySummary:
    return FactorLibrarySummary(**_summary_fields(row))


def _serialize_library_item(row: dict) -> FactorLibraryItem:
    """The detail shape. ``metrics`` rides along verbatim: the charts render it."""
    return FactorLibraryItem(
        **_summary_fields(row),
        code=row.get("code") or "",
        formulation=row.get("formulation") or "",
        variables=row.get("variables") or {},
        metrics=row.get("metrics") or {},
    )


def _not_found(factor_id: UUID) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"message": "因子不存在或不属于当前用户。", "kind": "not_found"},
    )


def _serialize(run: DetectionRun) -> DetectionRunResponse:
    payload = run.as_dict()
    return DetectionRunResponse(
        run_id=payload["run_id"],
        name=payload["name"],
        status=payload["status"],
        current_stage=payload["current_stage"],
        created_at=payload["created_at"],
        elapsed_sec=payload["elapsed_sec"],
        stages=[DetectionStage(**stage) for stage in payload["stages"]],
        findings=payload["findings"],
        verdict=payload["verdict"],
        error=payload["error"],
        error_kind=payload["error_kind"],
    )


@router.get("/health", response_model=FactorMinerHealthResponse)
async def factor_miner_health(user_id: CurrentUserId) -> FactorMinerHealthResponse:
    """Whether the board has a usable upstream, so the page can say so up front."""
    return FactorMinerHealthResponse(**await factor_miner.health())


@router.get("/templates", response_model=FactorTemplatesResponse)
async def list_templates(user_id: CurrentUserId) -> FactorTemplatesResponse:
    """Starter factors, one of which is the editor's default."""
    return FactorTemplatesResponse(
        templates=[FactorTemplate(**template) for template in FACTOR_TEMPLATES]
    )


@router.post("/detections", response_model=DetectionRunResponse, status_code=202)
async def create_detection(
    body: DetectionRequest, user_id: CurrentUserId
) -> DetectionRunResponse:
    """Start a detection and hand back its id.

    Fails fast on an unusable upstream: discovering that the service is down
    from a run that sits ``queued`` forever would be indistinguishable from a
    slow probe, and the user would have no reason to check the deployment.
    """
    if not factor_miner.factor_miner_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "message": "因子服务未配置：请设置 FACTOR_MINER_URL 指向 factor-miner（可用 hub 的 /hub/mcp/alpha 分组）。",
                "kind": "unavailable",
            },
        )

    run = start_detection(
        name=body.name, code=body.code, debug=body.debug, include_oos=body.include_oos
    )
    return _serialize(run)


@router.get("/detections", response_model=DetectionListResponse)
async def list_detections(user_id: CurrentUserId) -> DetectionListResponse:
    """Recent detections in this process, newest first."""
    return DetectionListResponse(runs=[_serialize(run) for run in recent_runs()])


@router.get("/detections/{run_id}", response_model=DetectionRunResponse)
async def get_detection(run_id: str, user_id: CurrentUserId) -> DetectionRunResponse:
    """Poll one detection.

    An unknown id is a 404 rather than an empty success: the ledger is
    process-local and expires, so a stale id after a restart is expected, and the
    page needs to tell that apart from "still running" to know to re-submit.
    """
    run = get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "检测记录不存在或已过期（后端重启会清空进行中的检测），请重新发起。",
                "kind": "not_found",
            },
        )
    return _serialize(run)


# ── Library ──────────────────────────────────────────────────────────────────


@router.get("/library", response_model=FactorLibraryListResponse)
async def list_library(
    user_id: CurrentUserId,
    status: str | None = Query(None, description="candidate | promoted | rejected"),
    source: str | None = Query(None, description="user | agent | sota | athena"),
    q: str | None = Query(None, description="Substring match on name or hypothesis"),
) -> FactorLibraryListResponse:
    """The library table, plus the counts the filter chips show."""
    rows, counts = await library.list_factors(
        user_id, status=status, source=source, query=q
    )
    return FactorLibraryListResponse(
        factors=[_serialize_library_summary(row) for row in rows], counts=counts
    )


@router.post("/library", response_model=FactorLibraryItem)
async def save_library_factor(
    body: FactorSaveRequest, user_id: CurrentUserId
) -> FactorLibraryItem:
    """Save a factor under its name (an existing name is updated, not duplicated).

    A 200 rather than a 201: the same call both creates and updates, and the
    client cannot tell which happened from the response — claiming "created"
    would be wrong half the time. An edited factor comes back re-evaluated-to-zero
    (metrics dropped, status back to ``candidate``), which the response shows.
    """
    try:
        row = await library.save_factor(
            user_id,
            name=body.name,
            hypothesis=body.hypothesis,
            code=body.code,
            description=body.description,
            formulation=body.formulation,
            variables=body.variables,
            source=body.source,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"message": str(exc), "kind": "invalid_factor"}
        ) from exc
    return _serialize_library_item(row)


@router.get("/library/{factor_id}", response_model=FactorLibraryItem)
async def get_library_factor(factor_id: UUID, user_id: CurrentUserId) -> FactorLibraryItem:
    """One factor in full. Scoped to the caller, so another user's id is a 404."""
    row = await library.get_factor(user_id, str(factor_id))
    if row is None:
        raise _not_found(factor_id)
    return _serialize_library_item(row)


@router.delete("/library/{factor_id}", status_code=204)
async def delete_library_factor(factor_id: UUID, user_id: CurrentUserId) -> None:
    """Delete a factor. Deleting an already-gone factor is a 404, not a no-op:
    the board refreshes off this call, and "it wasn't there" is worth telling."""
    if not await library.delete_factor(user_id, str(factor_id)):
        raise _not_found(factor_id)


@router.post("/library/{factor_id}/status", response_model=FactorLibraryItem)
async def set_library_status(
    factor_id: UUID, body: FactorStatusRequest, user_id: CurrentUserId
) -> FactorLibraryItem:
    """Promote, reject, or reopen a factor. The code and metrics are untouched."""
    try:
        row = await library.set_status(user_id, str(factor_id), body.status)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"message": str(exc), "kind": "invalid_status"}
        ) from exc
    if row is None:
        raise _not_found(factor_id)
    return _serialize_library_item(row)


@router.post("/library/{factor_id}/evaluate", response_model=FactorLibraryItem, status_code=202)
async def evaluate_library_factor(
    factor_id: UUID, body: FactorEvaluateRequest, user_id: CurrentUserId
) -> FactorLibraryItem:
    """Start a professional evaluation of a stored factor.

    Answers 202 with the row in ``running``: the evaluation scans a panel for
    seconds (``debug``) to minutes (``full``), so the page polls the same
    ``GET /library/{id}`` it already reads. A second request while one is fresh
    is a 409 — a full-panel scan is minutes of one machine's CPU, and queueing a
    duplicate behind it wastes the wait twice.
    """
    if not factor_miner.factor_miner_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "message": "因子服务未配置：请设置 FACTOR_MINER_URL 指向 factor-miner（可用 hub 的 /hub/mcp/alpha 分组）。",
                "kind": "unavailable",
            },
        )
    try:
        row = await library.start_evaluation(
            user_id,
            str(factor_id),
            dataset=body.dataset,
            quantiles=body.quantiles,
            periods=body.periods,
            window_days=body.window_days,
        )
    except EvaluationInFlight as exc:
        raise HTTPException(
            status_code=409, detail={"message": str(exc), "kind": "evaluation_in_flight"}
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"message": str(exc), "kind": "invalid_evaluation"}
        ) from exc
    if row is None:
        raise _not_found(factor_id)
    return _serialize_library_item(row)
