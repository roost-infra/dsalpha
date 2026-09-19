"""The factor library: saving a factor, moving it through its lifecycle, and
running the professional evaluation that fills in its metrics.

The board used to end at a verdict. This is what happens after: a factor is kept
(with the hypothesis that justifies it), evaluated on demand through the
factor-miner's ``factor_evaluate``, and promoted or rejected on the evidence.

Two decisions worth knowing before reading the code:

**Evaluation state lives in the row, not in this process.** A factor evaluation
scans a whole panel and takes minutes, so the POST cannot carry the answer -- but
the reply also cannot be a process-local run registry, because the backend serves
from several workers and the one that reads the next poll is not the one that
started the job. So ``metrics.evaluation`` in Postgres is the state, and this
module only *writes* it: ``running`` when the task starts, the full payload when
it finishes. A ``running`` row whose ``started_at`` is older than the transport's
own deadline is reported as ``lost`` rather than left spinning forever -- a worker
that dies mid-evaluation is a fact the user needs, not a hidden one.

**A failed evaluation replaces the metrics.** If the miner rejects the code or the
panel is too small, the reason is what the board should show; keeping the previous
successful tearsheet next to a failed re-run is how a stale number gets read as a
current one. ``last_evaluated_at`` is *not* stamped on failure -- nothing was
measured.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.config.settings import FACTOR_MINER_TIMEOUT
from src.server.database import factor_library as db
from src.server.services import factor_miner
from src.server.services.factor_miner import FactorMinerError

logger = logging.getLogger(__name__)

# Who wrote the factor. Rendered on the board because a promoted SOTA baseline and
# a model's guess are not the same claim.
FACTOR_SOURCES = ("user", "agent", "sota", "athena")

# The lifecycle. `candidate` is where everything starts, `promoted` is the
# admission decision, `rejected` keeps the record rather than deleting it.
FACTOR_STATUSES = ("candidate", "promoted", "rejected")

# The miner's two panels: `debug` is a small static set (seconds), `full` is the
# windowed production panel (minutes). The board defaults to `debug` so a click
# answers, and `full` is the deliberate production-grade re-run.
EVALUATION_DATASETS = ("debug", "full")
DEFAULT_EVALUATION_DATASET = "debug"

# A trailing window for the full panel. Long enough to give the quantile and IC
# statistics a real sample (a trading year), short enough that the tearsheet does
# not spend its time on a decade the factor will never be used over.
DEFAULT_FULL_WINDOW_DAYS = 250

# Evaluation states as the board sees them: `none` (never run), `running`,
# `done`, `failed`, `lost` (a started run whose worker went away).
EVALUATION_STATE_NONE = "none"
EVALUATION_STATE_RUNNING = "running"
EVALUATION_STATE_DONE = "done"
EVALUATION_STATE_FAILED = "failed"
EVALUATION_STATE_LOST = "lost"

# Beyond the transport's own deadline, nothing can still be working on a call it
# started; the row is a leftover from a worker that died (or was replaced). A
# minute of slack covers clock skew between the write and the poll.
_STALE_AFTER = timedelta(seconds=FACTOR_MINER_TIMEOUT + 60)

# Background evaluation tasks. Held so the loop cannot garbage-collect a task
# mid-flight -- an un-referenced task is the classic way a job disappears without
# a log line. This set is execution context only: nothing reads it to decide what
# a factor's state is (that is the row).
_tasks: set[asyncio.Task] = set()

# Periods follow the miner's own bound: past ~120 trading days a forward return
# stops being a holding period anyone trades.
_MAX_PERIOD_DAYS = 120


class EvaluationInFlight(RuntimeError):
    """A fresh evaluation is already running for this factor."""


def normalize_periods(periods: list[Any] | None) -> list[int]:
    """Positive integers, deduped, ascending, capped; empty means the default."""
    out: list[int] = []
    for raw in periods or (1, 5, 10):
        try:
            days = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= days <= _MAX_PERIOD_DAYS and days not in out:
            out.append(days)
    return sorted(out) or [1, 5, 10]


def normalize_quantiles(quantiles: Any) -> int:
    """At least two buckets (one bucket has no spread) and at most ten."""
    try:
        value = int(quantiles)
    except (TypeError, ValueError):
        return 5
    return max(2, min(10, value))


def normalize_dataset(dataset: Any) -> str:
    value = str(dataset or "").strip().lower()
    return value if value in EVALUATION_DATASETS else DEFAULT_EVALUATION_DATASET


def _parse_time(value: Any) -> datetime | None:
    """Read a stored ISO timestamp back, tolerating anything a JSON column holds."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)  # py3.11+ parses the trailing Z of a UTC stamp
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def evaluation_state(metrics: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """The evaluation block a reader should act on, staleness resolved.

    A row is the only record that an evaluation happened, so a ``running`` mark
    whose writer is gone must not be reported as still working: the user would
    wait on a job nobody holds. Past the transport deadline the state becomes
    ``lost``, which is an actionable answer ("run it again") rather than a spinner.
    """
    block = dict((metrics or {}).get("evaluation") or {})
    state = str(block.get("state") or "")
    if not state:
        # A row written before this field existed, or one evaluated by hand, still
        # has to report something true: metrics that carry a tearsheet are `done`.
        state = EVALUATION_STATE_DONE if (metrics or {}).get("tearsheet") else EVALUATION_STATE_NONE
    if state == EVALUATION_STATE_RUNNING:
        started = _parse_time(block.get("started_at"))
        if started is not None and (now or datetime.now(UTC)) - started > _STALE_AFTER:
            block["state"] = EVALUATION_STATE_LOST
            block["error"] = "评估进程已消失（后端重启或超时），请重新发起。"
            block["error_kind"] = "lost"
            return block
    block["state"] = state
    return block


def build_metrics(
    payload: dict[str, Any],
    *,
    dataset: str,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    """Shape the miner's ``factor_evaluate`` answer into the stored metrics.

    The tearsheet is stored verbatim -- it is another service's contract and the
    charts render it as it arrives. The handful of lifted fields (IC, IR, t,
    half-life) are what the *list* sorts and filters on, so they do not have to be
    dug out of a nested object per row.
    """
    tearsheet = payload.get("tearsheet") or {}
    ic = (tearsheet.get("ic") or {}) if isinstance(tearsheet, dict) else {}
    return {
        "ic": ic.get("mean"),
        "ir": ic.get("ir"),
        "t_stat": payload.get("ic_t_stat"),
        "ic_half_life_days": payload.get("ic_half_life_days"),
        "monotonicity": payload.get("monotonicity") or {},
        "tearsheet": tearsheet,
        "evaluation": {
            "state": EVALUATION_STATE_DONE,
            "dataset": dataset,
            "window_days": payload.get("window_days"),
            "quantiles": payload.get("quantiles"),
            "periods": payload.get("periods"),
            "n_dates": payload.get("n_dates"),
            "n_symbols": payload.get("n_symbols"),
            "eval_window": payload.get("eval_window") or {},
            "hypothesis_missing": bool(payload.get("hypothesis_missing")),
            "started_at": started_at,
            "finished_at": finished_at,
            "error": "",
            "error_kind": "",
        },
    }


def build_failure_metrics(
    *,
    dataset: str,
    started_at: str,
    error: str,
    error_kind: str,
) -> dict[str, Any]:
    """A failed evaluation's metrics: the reason, and nothing that looks measured."""
    return {
        "evaluation": {
            "state": EVALUATION_STATE_FAILED,
            "dataset": dataset,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "error": error,
            "error_kind": error_kind,
        }
    }


def _running_metrics(
    previous: dict[str, Any] | None, *, dataset: str, started_at: str
) -> dict[str, Any]:
    """The metrics as they read *while* the evaluation runs.

    The previous tearsheet is kept: it is still the last thing that was measured,
    and blanking the charts for the minutes a re-run takes would make a working
    factor look broken. The state is what tells the reader it is being replaced.
    """
    metrics = dict(previous or {})
    metrics["evaluation"] = {
        "state": EVALUATION_STATE_RUNNING,
        "dataset": dataset,
        "started_at": started_at,
        "error": "",
        "error_kind": "",
    }
    return metrics


async def save_factor(
    user_id: str,
    *,
    name: str,
    hypothesis: str,
    code: str,
    description: str = "",
    formulation: str = "",
    variables: dict[str, Any] | None = None,
    source: str = "user",
) -> dict[str, Any]:
    """Save a factor, refusing the one thing that makes it unprofessional.

    The hypothesis check is repeated here even though the request model enforces
    it: a factor can also arrive from the detection flow or an import path, and a
    library of unexplained factors is exactly the failure this table's NOT NULL is
    there to prevent.
    """
    hypothesis = (hypothesis or "").strip()
    if not hypothesis:
        raise ValueError("经济假设不能为空：没有假设的因子是数据挖掘，无法入库。")
    name = (name or "").strip()
    if not name:
        raise ValueError("因子名称不能为空。")
    if source not in FACTOR_SOURCES:
        source = "user"
    return await db.save_factor(
        user_id,
        name=name,
        hypothesis=hypothesis,
        code=code,
        description=description or "",
        formulation=formulation or "",
        variables=variables,
        source=source,
    )


async def list_factors(
    user_id: str,
    *,
    status: str | None = None,
    source: str | None = None,
    query: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The library page: the rows plus the counts its filter chips show."""
    status = status if status in FACTOR_STATUSES else None
    source = source if source in FACTOR_SOURCES else None
    rows = await db.list_factors(
        user_id, status=status, source=source, query=(query or "").strip() or None
    )
    return rows, await db.status_counts(user_id)


async def get_factor(user_id: str, factor_id: str) -> dict[str, Any] | None:
    return await db.get_factor(user_id, factor_id)


async def set_status(user_id: str, factor_id: str, status: str) -> dict[str, Any] | None:
    if status not in FACTOR_STATUSES:
        raise ValueError(f"未知状态 {status!r}；可用：{', '.join(FACTOR_STATUSES)}")
    return await db.set_status(user_id, factor_id, status)


async def delete_factor(user_id: str, factor_id: str) -> bool:
    return await db.delete_factor(user_id, factor_id)


async def start_evaluation(
    user_id: str,
    factor_id: str,
    *,
    dataset: str = DEFAULT_EVALUATION_DATASET,
    quantiles: int = 5,
    periods: list[Any] | None = None,
    window_days: int | None = None,
) -> dict[str, Any] | None:
    """Mark the factor as evaluating and run it on the event loop.

    Returns the row as it now reads (state ``running``), or None when the factor
    is not the caller's. Raises :class:`EvaluationInFlight` when a fresh run is
    already going: the full panel is minutes of one machine's CPU, so a second
    click must not queue a second scan behind the first.
    """
    row = await db.get_factor(user_id, factor_id)
    if row is None:
        return None

    state = evaluation_state(row.get("metrics"))
    if state.get("state") == EVALUATION_STATE_RUNNING:
        raise EvaluationInFlight("该因子正在评估中，请等待本次完成。")

    dataset = normalize_dataset(dataset)
    quantiles = normalize_quantiles(quantiles)
    period_list = normalize_periods(periods)
    if dataset == "full":
        days = window_days if window_days is not None else DEFAULT_FULL_WINDOW_DAYS
        window = max(20, min(1000, int(days)))
    else:
        # The debug panel is a fixed small slice; a window would truncate it.
        window = 0

    started_at = datetime.now(UTC).isoformat()
    updated = await db.write_metrics(
        user_id,
        factor_id,
        metrics=_running_metrics(row.get("metrics"), dataset=dataset, started_at=started_at),
        measured=False,
    )
    if updated is None:
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:  # pragma: no cover — request paths always have one
        raise RuntimeError("start_evaluation must be called from a running event loop") from exc

    task = loop.create_task(
        _run_evaluation(
            user_id,
            factor_id,
            code=row["code"],
            hypothesis=row["hypothesis"],
            dataset=dataset,
            quantiles=quantiles,
            periods=period_list,
            window_days=window,
            started_at=started_at,
        )
    )
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    logger.info(
        "factor evaluation started: factor=%s dataset=%s quantiles=%s periods=%s",
        factor_id,
        dataset,
        quantiles,
        period_list,
    )
    return updated


async def _run_evaluation(
    user_id: str,
    factor_id: str,
    *,
    code: str,
    hypothesis: str,
    dataset: str,
    quantiles: int,
    periods: list[int],
    window_days: int,
    started_at: str,
) -> None:
    """Run one evaluation and persist its outcome, whatever the outcome is.

    Nothing here may raise: a task that dies silently leaves the row ``running``
    until it is reaped as ``lost``, which turns a diagnosable failure into a
    mystery. Every exit writes the row.
    """
    arguments: dict[str, Any] = {
        "code": code,
        "hypothesis": hypothesis,
        "quantiles": quantiles,
        "periods": periods,
        "dataset": dataset,
    }
    # The miner's debug panel is a fixed slice; passing a window would truncate it.
    if dataset == "full":
        arguments["window_days"] = window_days

    try:
        payload = await factor_miner.call_tool("factor_evaluate", arguments)
    except FactorMinerError as exc:
        logger.warning("factor evaluation failed: factor=%s kind=%s %s", factor_id, exc.kind, exc.message)
        await _fail(user_id, factor_id, dataset, started_at, exc.message, exc.kind)
        return
    except Exception as exc:
        logger.exception("factor evaluation raised: factor=%s", factor_id)
        await _fail(
            user_id, factor_id, dataset, started_at, f"评估内部错误：{exc}", "internal"
        )
        return

    if not payload.get("ok"):
        reason = str(payload.get("error") or "评估未通过")
        await _fail(user_id, factor_id, dataset, started_at, reason, "upstream")
        return

    metrics = build_metrics(
        payload,
        dataset=dataset,
        started_at=started_at,
        finished_at=datetime.now(UTC).isoformat(),
    )
    await db.write_metrics(user_id, factor_id, metrics=metrics, measured=True)
    logger.info(
        "factor evaluation done: factor=%s ic=%s ir=%s",
        factor_id,
        metrics.get("ic"),
        metrics.get("ir"),
    )


async def _fail(
    user_id: str,
    factor_id: str,
    dataset: str,
    started_at: str,
    error: str,
    error_kind: str,
) -> None:
    await db.write_metrics(
        user_id,
        factor_id,
        metrics=build_failure_metrics(
            dataset=dataset, started_at=started_at, error=error, error_kind=error_kind
        ),
        measured=False,
    )
