"""Factor Board API — one-click factor detection over the factor-miner service.

Three resources, all user-scoped like every other page-backed router here:

- ``GET  /api/v1/factors/templates``  the scripts the editor offers
- ``POST /api/v1/factors/detections`` start a detection, return its id at once
- ``GET  /api/v1/factors/detections/{id}`` poll it

The submit/poll split is forced by the upstream: the contract check returns in
seconds but the IC probes scan the full panel for minutes, so the POST cannot
carry the answer. It returns a run in ``queued`` and the page polls, which is
also what lets the progress list be real instead of a spinner.
"""

import logging

from fastapi import APIRouter, HTTPException

from src.server.models.factor import (
    DetectionListResponse,
    DetectionRequest,
    DetectionRunResponse,
    DetectionStage,
    FactorMinerHealthResponse,
    FactorTemplate,
    FactorTemplatesResponse,
)
from src.server.services import factor_miner
from src.server.services.factor_detection import (
    FACTOR_TEMPLATES,
    DetectionRun,
    get_run,
    recent_runs,
    start_detection,
)
from src.server.utils.api import CurrentUserId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/factors", tags=["Factor Board"])


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
