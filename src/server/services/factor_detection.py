"""One-click factor detection, and the run ledger the page reads.

The Factor Board's whole point is that a factor author does not have to know
which probe to run where: they hand over code and get a verdict. That makes this
module the composition layer over three factor-miner tools, plus the small
amount of bookkeeping a page needs to show progress while they run.

**Why a ledger and not a plain await.** The contract check runs on a two-year
debug panel and returns in seconds, but the IC probes scan the full panel and
take minutes — measured at ~280s for a single 60-day window. A request that
awaited them would be a request nobody can hold open. So a detection is a run:
submit returns an id immediately, the probes advance in the background, and the
page polls. Progress is published stage by stage, which is what makes a
four-minute wait legible instead of a spinner.

**Runs live in this process.** The tracker is deliberately process-local: a
detection is a short-lived interactive job, not a durable artifact, and the
alternative (a Postgres table plus a worker) buys durability this feature does
not ask for. The cost is honest and bounded — a restart drops in-flight runs, so
the page sees a stale id and re-submits. That is why every run carries a
``status`` the UI can act on rather than assuming it will always resolve.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.server.services import factor_miner
from src.server.services.factor_miner import FactorMinerError

logger = logging.getLogger(__name__)

# A finished run is kept long enough for a page to come back to it, then
# dropped. Nothing reads history, so this is the only thing bounding memory.
RUN_TTL_SECONDS = 3600.0

# Lookback windows probed for decay. Two points rather than one: a factor that
# only holds up over one horizon is a different finding from one that holds up
# over both, and the comparison costs one extra probe in the background.
RECENT_IC_WINDOWS = (20, 60)


@dataclass
class Stage:
    key: str
    label: str
    state: str = "pending"  # pending | running | done | failed | skipped
    detail: str = ""
    started_at: float | None = None
    finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "state": self.state,
            "detail": self.detail,
            "elapsed_sec": (
                round((self.finished_at or time.time()) - self.started_at, 1)
                if self.started_at
                else None
            ),
        }


@dataclass
class DetectionRun:
    """One detection, from submission to verdict."""

    id: str
    name: str
    code: str
    debug: bool
    created_at: float = field(default_factory=time.time)
    status: str = "queued"  # queued | running | done | failed
    current_stage: str = ""
    error: str = ""
    error_kind: str = ""
    stages: list[Stage] = field(default_factory=list)
    findings: dict[str, Any] = field(default_factory=dict)
    verdict: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.id,
            "name": self.name,
            "status": self.status,
            "current_stage": self.current_stage,
            "created_at": self.created_at,
            "elapsed_sec": round(time.time() - self.created_at, 1),
            "stages": [s.as_dict() for s in self.stages],
            "findings": self.findings,
            "verdict": self.verdict,
            "error": self.error,
            "error_kind": self.error_kind,
        }


_runs: dict[str, DetectionRun] = {}
_tasks: set[asyncio.Task] = set()


def _prune() -> None:
    """Drop settled runs past their TTL.

    Called from the reads as well as from submit: a process that takes one
    detection an hour and is otherwise idle would otherwise hold every run it
    ever made, and the only thing bounding the ledger would be someone else's
    traffic. Runs still in flight are never pruned — their TTL describes how long
    a finished run stays answerable, not how long a probe may take.
    """
    cutoff = time.time() - RUN_TTL_SECONDS
    for run_id in [
        rid
        for rid, run in _runs.items()
        if run.created_at < cutoff and run.status in ("done", "failed")
    ]:
        _runs.pop(run_id, None)


def get_run(run_id: str) -> DetectionRun | None:
    _prune()
    return _runs.get(run_id)


def recent_runs(limit: int = 20) -> list[DetectionRun]:
    _prune()
    return sorted(_runs.values(), key=lambda r: r.created_at, reverse=True)[:limit]


# ── Verdict ──────────────────────────────────────────────────────────────────
#
# The thresholds are the reading of the IC scale this desk uses: a cross-
# sectional IC of ~0.02 is the floor where a factor still pays after costs, and
# ~0.05 is strong for a single daily signal. They are stated once, here, so the
# page and the API cannot disagree about what "strong" means.
IC_WEAK_BELOW = 0.02
IC_STRONG_AT = 0.05


def _rate_ic(ic: float) -> tuple[str, str]:
    magnitude = abs(ic)
    if magnitude >= IC_STRONG_AT:
        return "strong", "strong"
    if magnitude >= IC_WEAK_BELOW:
        return "present", "moderate"
    return "faint", "weak"


def build_verdict(run: DetectionRun) -> dict[str, Any]:
    """Turn the raw findings into the one sentence the page leads with.

    A factor is only judged on its IC once it has cleared the contract check —
    an IC computed over output that violates the panel shape is not evidence
    about the factor, so a contract failure short-circuits to "invalid" instead
    of reporting a number that would be misread as merit.
    """
    contract = run.findings.get("contract") or {}
    probes: list[dict[str, Any]] = run.findings.get("recent_ic") or []
    oos = run.findings.get("oos") or {}

    usable = [p for p in probes if isinstance(p.get("ic"), (int, float))]
    best = max(usable, key=lambda p: abs(p["ic"])) if usable else None

    if contract and not contract.get("ok"):
        return {
            "level": "invalid",
            "label": "未通过契约检查",
            "summary": str(contract.get("detail") or "factor.py 未产出符合规范的 result.h5"),
            "ic": None,
            "ic_label": None,
        }

    if not usable:
        return {
            "level": "unknown",
            "label": "检测无有效结果",
            "summary": "因子跑通了，但没有取到有效的截面 IC —— 请检查样本区间或数据覆盖。",
            "ic": None,
            "ic_label": None,
        }

    level, ic_label = _rate_ic(float(best["ic"]))
    parts = [f"{best['window']} 日截面 IC {best['ic']:+.4f}"]
    if oos.get("decay") is not None:
        parts.append(f"样本外衰减 {float(oos['decay']):+.1%}")

    summary = "；".join(parts)
    if level == "faint":
        summary += " —— 低于可交易阈值，建议放弃或重构。"

    return {
        "level": level,
        "label": {"strong": "强因子", "present": "有效因子", "faint": "弱因子"}[level],
        "summary": summary,
        "ic": float(best["ic"]),
        "ic_label": ic_label,
    }


# ── Stages ───────────────────────────────────────────────────────────────────

# The contract check runs in a sandbox with a hard 120s ceiling, and the same
# script has been measured at 6s and at 49s — so a timeout is a statement about
# load, not about the factor. One extra attempt converts most of those into a
# pass at a bounded cost (2 minutes, only on the failure path); a factor that is
# genuinely too slow times out twice and is reported as such.
CONTRACT_ATTEMPTS = 2
_SANDBOX_TIMEOUT_MARKER = "sandbox timeout"


async def _stage_contract(run: DetectionRun) -> None:
    """Shape check on the debug panel — the part that fails fast and loudly."""
    payload: dict[str, Any] = {}
    for attempt in range(CONTRACT_ATTEMPTS):
        payload = await factor_miner.call_tool(
            "factor_execute", {"code": run.code, "debug": True}
        )
        detail = str(payload.get("eval_detail") or "")
        if payload.get("eval_ok") or _SANDBOX_TIMEOUT_MARKER not in detail:
            break
        if attempt + 1 < CONTRACT_ATTEMPTS:
            logger.info(
                "contract check for %s hit the sandbox ceiling; retrying once", run.name
            )

    ok = bool(payload.get("eval_ok"))
    run.findings["contract"] = {
        "ok": ok,
        "detail": str(payload.get("eval_detail") or ""),
        "stdout": str(payload.get("stdout") or ""),
        "dataset": payload.get("dataset"),
    }
    if not ok:
        raise FactorMinerError("factor", str(payload.get("eval_detail") or "契约检查未通过"))


async def _stage_recent_ic(run: DetectionRun, window: int) -> dict[str, Any]:
    """Trailing cross-sectional IC over ``window`` trading days.

    ``ok`` is not trusted as the success signal: the service has answered
    ``ok: true`` alongside an ``error`` string, so the probe counts as usable
    only when it actually carries a number.

    ``series`` is the per-day IC breakdown the board draws as a decay curve. It
    is passed through verbatim (``[{date, ic, n}]``) rather than re-derived here:
    the miner already computed it from the same groupby that produced ``ic``, so
    recomputing would mean a second full panel read for no new information.
    """
    payload = await factor_miner.call_tool(
        "factor_recent_ic", {"code": run.code, "name": run.name, "lookback_days": window}
    )
    ic = payload.get("ic")
    series = payload.get("series")
    return {
        "window": window,
        "ic": float(ic) if isinstance(ic, (int, float)) else None,
        "days": payload.get("days"),
        "series": series if isinstance(series, list) else [],
        "error": str(payload.get("error") or ""),
    }


async def _stage_oos(run: DetectionRun) -> None:
    payload = await factor_miner.call_tool("factor_oos_check", {"code": run.code, "name": run.name})
    run.findings["oos"] = {
        "mining": payload.get("mining"),
        "oos": payload.get("oos"),
        "decay": payload.get("decay"),
        # 两条净值曲线原样透传（miner 已抽稀到 <=400 点）。不在这里加工：曲线的
        # 日期与数值口径都来自 qlib 那份 report，重算会引入偏差。
        "mining_net_curve": payload.get("mining_net_curve") or [],
        "oos_net_curve": payload.get("oos_net_curve") or [],
        # The tool can answer `status: done` while carrying its own failure in
        # `ok`/`error` — that is how a worker-side crash arrives when the queue
        # swallowed the exception. Passed through so the stage can fail loudly
        # instead of rendering two empty columns as if they were results.
        "ok": payload.get("ok"),
        "error": payload.get("error"),
    }
    if not payload.get("mining") and not payload.get("oos"):
        raise FactorMinerError("upstream", str(payload.get("error") or "样本外检验没有返回结果"))


async def _advance(run: DetectionRun) -> None:
    """Drive the stages in order, publishing progress as each one starts."""
    run.status = "running"
    contract = run.stages[0]
    try:
        contract.state = "running"
        contract.started_at = time.time()
        run.current_stage = "contract"
        await _stage_contract(run)
        contract.state = "done"
        contract.finished_at = time.time()
        contract.detail = str((run.findings.get("contract") or {}).get("detail") or "通过")
    except FactorMinerError as exc:
        contract.state = "failed"
        contract.finished_at = time.time()
        contract.detail = exc.message
        for stage in run.stages[1:]:
            stage.state = "skipped"
        raise

    # The probes run one after another on purpose. `factor_recent_ic` is a
    # synchronous tool, and the miner's queue serves it from a two-worker pool —
    # firing both windows at once would occupy the whole pool for the duration of
    # a detection and starve every other caller, including the agent's own mining
    # runs. Sequential costs wall-clock time; concurrent costs the service.
    probe_stages = run.stages[1 : 1 + len(RECENT_IC_WINDOWS)]
    run.current_stage = "recent_ic"

    probes: list[dict[str, Any]] = []
    for index, (stage, window) in enumerate(zip(probe_stages, RECENT_IC_WINDOWS)):
        stage.state = "running"
        stage.started_at = time.time()
        try:
            result = await _stage_recent_ic(run, window)
        except FactorMinerError as exc:
            stage.state = "failed"
            stage.finished_at = time.time()
            stage.detail = exc.message
            # A probe that could not run means the panel or the transport is
            # unavailable, and the next window asks the same question of the same
            # panel — it would spend another ~five minutes to fail the same way.
            # The run is already decided, so the remaining windows are marked
            # skipped rather than paid for.
            for later in probe_stages[index + 1 :]:
                later.state = "skipped"
                later.detail = "前一个窗口未取到结果"
            break
        probes.append(result)
        stage.state = "done"
        stage.finished_at = time.time()
        stage.detail = (
            f"IC {result['ic']:+.4f}" if isinstance(result.get("ic"), (int, float)) else "无有效 IC"
        )
    run.findings["recent_ic"] = probes

    oos_stage = run.stages[-1]
    oos_stage.state = "running"
    oos_stage.started_at = time.time()
    run.current_stage = "oos"
    try:
        await _stage_oos(run)
        oos_stage.state = "done"
        decay = (run.findings.get("oos") or {}).get("decay")
        oos_stage.detail = f"衰减 {float(decay):+.1%}" if decay is not None else "完成"
    except FactorMinerError as exc:
        # OOS is the advisory stage: it refines the verdict, it does not gate it,
        # so a failure here leaves the IC verdict standing.
        oos_stage.state = "failed"
        oos_stage.detail = exc.message
    oos_stage.finished_at = time.time()


def _stage_plan(include_oos: bool) -> list[Stage]:
    stages = [Stage("contract", "契约检查", detail="result.h5 形状与沙箱约束")]
    for window in RECENT_IC_WINDOWS:
        stages.append(Stage(f"recent_ic_{window}", f"近 {window} 日 IC", detail="截面预测力"))
    if include_oos:
        stages.append(Stage("oos", "样本外检验", detail="挖掘窗 vs 样本外窗"))
    return stages


async def _run_detection(run: DetectionRun) -> None:
    try:
        await _advance(run)
        run.verdict = build_verdict(run)
        run.status = "done"
        run.current_stage = ""
    except FactorMinerError as exc:
        run.status = "failed"
        run.error = exc.message
        run.error_kind = exc.kind
        run.verdict = build_verdict(run)
        run.current_stage = ""
    except asyncio.CancelledError:
        run.status = "failed"
        run.error = "检测被取消"
        run.error_kind = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001 — a background task may not vanish silently
        logger.exception("factor detection %s crashed", run.id)
        run.status = "failed"
        run.error = f"检测内部错误：{exc}"
        run.error_kind = "internal"
        run.verdict = build_verdict(run)
        run.current_stage = ""


def start_detection(name: str, code: str, *, debug: bool = True, include_oos: bool = True) -> DetectionRun:
    """Register a run and start it on the event loop.

    The task is held in a module-level set: an un-referenced task can be garbage
    collected mid-flight, which is the classic way a background job disappears
    without a log line.

    Callers must be on a running loop — the request path always is. Asserted
    rather than papered over with an implicit loop, because `create_task` with no
    loop raises *after* the run is registered, which would leave a run in the
    ledger that nothing will ever advance.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        raise RuntimeError("start_detection must be called from a running event loop") from exc

    _prune()
    run = DetectionRun(
        id=uuid.uuid4().hex[:12],
        name=name or "factor",
        code=code,
        debug=debug,
        stages=_stage_plan(include_oos),
    )
    _runs[run.id] = run
    task = loop.create_task(_run_detection(run))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    logger.info("factor detection %s started for %s", run.id, run.name)
    return run


# ── Templates ────────────────────────────────────────────────────────────────
#
# The sandbox panel is a Fixed-format HDF store under a MultiIndex, which cannot
# be read by column and must not be unstacked (the 2GB address-space ceiling in
# factor-miner's own template is a real failure, not a style note). These are the
# shapes that satisfy that contract, kept short enough to read in the editor.
FACTOR_TEMPLATES: list[dict[str, str]] = [
    {
        "key": "reversal_20",
        "name": "20 日反转",
        "description": "过去 20 个交易日跌幅越大、次日越可能反弹。经典短期反转。",
        "code": '''import pandas as pd

# 整体读入（Fixed 格式不能按列读），随后只留一列
df = pd.read_hdf("daily_pv.h5", key="data")
close = df["$close"].sort_index()
del df

# 长表上按标的算因子，不要 unstack（会顶爆沙箱地址空间）
factor = -close.groupby(level="instrument").pct_change(20)
factor.name = "factor"

factor.to_frame().to_hdf("result.h5", key="data")
''',
    },
    {
        "key": "momentum_60",
        "name": "60 日动量",
        "description": "中期强者恒强。与 20 日反转方向相反，适合做对比。",
        "code": '''import pandas as pd

df = pd.read_hdf("daily_pv.h5", key="data")
close = df["$close"].sort_index()
del df

factor = close.groupby(level="instrument").pct_change(60)
factor.name = "factor"

factor.to_frame().to_hdf("result.h5", key="data")
''',
    },
    {
        "key": "volatility_20",
        "name": "20 日波动率",
        "description": "低波动异象：波动越低，风险调整后收益往往越高。",
        "code": '''import pandas as pd

df = pd.read_hdf("daily_pv.h5", key="data")
ret = df["$close"].sort_index().groupby(level="instrument").pct_change()
del df

# 取负号，使“低波动”得高分
factor = -ret.groupby(level="instrument").rolling(20).std().droplevel(0)
factor.name = "factor"

factor.to_frame().to_hdf("result.h5", key="data")
''',
    },
    {
        "key": "volume_ratio",
        "name": "量比异动",
        "description": "当日成交量相对 20 日均量的放大倍数，捕捉资金异动。",
        "code": '''import pandas as pd

df = pd.read_hdf("daily_pv.h5", key="data")
volume = df["$volume"].sort_index()
del df

mean20 = volume.groupby(level="instrument").rolling(20).mean().droplevel(0)
factor = volume / mean20.replace(0, pd.NA)
factor.name = "factor"

factor.to_frame().to_hdf("result.h5", key="data")
''',
    },
]


def template_by_key(key: str) -> dict[str, str] | None:
    for template in FACTOR_TEMPLATES:
        if template["key"] == key:
            return template
    return None
