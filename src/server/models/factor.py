"""Pydantic models for the Factor Board endpoints.

The response shapes are declared rather than left as bare dicts so the OpenAPI
document is the contract the web client codes against: the detection page reads
``stages`` for its progress list, ``findings`` for the IC panel, and ``verdict``
for the headline, and each of those has to keep its field names.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# A factor is a short script. The cap is not about storage: the code is posted to
# the sandbox and an unbounded body would let a client push megabytes through a
# request path nobody rate-limits.
MAX_FACTOR_CODE_BYTES = 64 * 1024


class FactorTemplate(BaseModel):
    """A ready-to-run factor script offered in the editor."""

    key: str = Field(..., description="Stable identifier")
    name: str = Field(..., description="Display name")
    description: str = Field(..., description="What the factor claims to capture")
    code: str = Field(..., description="The factor.py source")


class FactorTemplatesResponse(BaseModel):
    templates: list[FactorTemplate]


class DetectionRequest(BaseModel):
    """Submit factor code for a one-click detection."""

    name: str = Field("factor", description="Factor name, used in reports", max_length=64)
    code: str = Field(..., description="factor.py source satisfying the result.h5 contract")
    debug: bool = Field(True, description="Run the contract check on the debug panel")
    include_oos: bool = Field(True, description="Also run the out-of-sample comparison")

    @field_validator("code")
    @classmethod
    def code_must_be_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("factor code is empty")
        if len(value.encode("utf-8")) > MAX_FACTOR_CODE_BYTES:
            raise ValueError(f"factor code exceeds {MAX_FACTOR_CODE_BYTES} bytes")
        return value


class DetectionStage(BaseModel):
    key: str
    label: str
    state: str = Field(..., description="pending | running | done | failed | skipped")
    detail: str = ""
    elapsed_sec: float | None = None


class DetectionRunResponse(BaseModel):
    """One detection, either in flight or finished.

    Deliberately not split into a status model and a result model: the page polls
    a single id, and a single shape means the poll response can be rendered
    without branching on which endpoint produced it.
    """

    run_id: str
    name: str
    status: str = Field(..., description="queued | running | done | failed")
    current_stage: str = ""
    created_at: float
    elapsed_sec: float
    stages: list[DetectionStage] = Field(default_factory=list)
    findings: dict[str, Any] = Field(default_factory=dict)
    verdict: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    error_kind: str = ""


class DetectionListResponse(BaseModel):
    runs: list[DetectionRunResponse]


class FactorMinerHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    configured: bool
    reachable: bool
    url: str = ""


# ── Factor library ───────────────────────────────────────────────────────────
#
# The list and the detail are separate shapes on purpose. A list row carries the
# columns the table shows (name, hypothesis, status, IC/IR); the detail adds the
# code, the formulation and the full tearsheet. One shape for both would ship
# every factor's code and metrics to render a table.

# The lifecycle, mirrored from services.factor_library so a bad body is a 422 with
# the same wording the service would use.
FACTOR_STATUS_VALUES = ("candidate", "promoted", "rejected")
FACTOR_SOURCE_VALUES = ("user", "agent", "sota", "athena")


class FactorLibrarySummary(BaseModel):
    """One row of the board's factor table."""

    factor_id: str
    name: str
    hypothesis: str = Field(..., description="The economic reason this factor should work")
    description: str = ""
    source: str = Field("user", description="user | agent | sota | athena")
    status: str = Field("candidate", description="candidate | promoted | rejected")
    code_hash: str = ""
    ic: float | None = Field(None, description="Mean cross-sectional IC of the last evaluation")
    ir: float | None = Field(None, description="IC information ratio (mean / std)")
    t_stat: float | None = Field(None, description="IC t-statistic; significance before size")
    ic_half_life_days: float | None = Field(
        None, description="Trading days for |IC| to halve; null when IC does not decay"
    )
    monotonicity: dict[str, Any] = Field(
        default_factory=dict, description="Strict quantile monotonicity per forward period"
    )
    evaluation: dict[str, Any] = Field(
        default_factory=dict,
        description="Resolved evaluation state: none | running | done | failed | lost, with the reason",
    )
    last_evaluated_at: datetime | None = None
    promoted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FactorLibraryItem(FactorLibrarySummary):
    """One factor in full — what the detail panel renders, charts included."""

    code: str = ""
    formulation: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(
        default_factory=dict, description="Raw stored metrics: tearsheet + the evaluation block"
    )


class FactorLibraryListResponse(BaseModel):
    factors: list[FactorLibrarySummary] = Field(default_factory=list)
    counts: dict[str, int] = Field(
        default_factory=dict, description="total / candidate / promoted / rejected / evaluated"
    )


class FactorSaveRequest(BaseModel):
    """Save a factor to the library.

    ``hypothesis`` is required and validated for content, not just presence: the
    library refuses unexplained factors, and a 422 here is the cheapest place to
    say so.
    """

    name: str = Field(..., description="Factor name, unique per user", max_length=64)
    hypothesis: str = Field(..., description="Economic hypothesis (required)")
    code: str = Field(..., description="factor.py source satisfying the result.h5 contract")
    description: str = Field("", description="One-line summary for the list")
    formulation: str = Field("", description="The formula, for the detail panel")
    variables: dict[str, Any] = Field(default_factory=dict, description="Input variables")
    source: str = Field("user", description="user | agent | sota | athena")

    @field_validator("name")
    @classmethod
    def name_must_be_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("因子名称不能为空")
        return value.strip()

    @field_validator("hypothesis")
    @classmethod
    def hypothesis_must_say_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("经济假设不能为空：没有假设的因子是数据挖掘，无法入库")
        return value.strip()

    @field_validator("code")
    @classmethod
    def code_must_be_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("factor code is empty")
        if len(value.encode("utf-8")) > MAX_FACTOR_CODE_BYTES:
            raise ValueError(f"factor code exceeds {MAX_FACTOR_CODE_BYTES} bytes")
        return value

    @field_validator("source")
    @classmethod
    def source_must_be_known(cls, value: str) -> str:
        if value not in FACTOR_SOURCE_VALUES:
            raise ValueError(f"未知来源 {value!r}；可用：{', '.join(FACTOR_SOURCE_VALUES)}")
        return value


class FactorStatusRequest(BaseModel):
    """Move a factor through its lifecycle."""

    status: str = Field(..., description="candidate | promoted | rejected")

    @field_validator("status")
    @classmethod
    def status_must_be_known(cls, value: str) -> str:
        if value not in FACTOR_STATUS_VALUES:
            raise ValueError(f"未知状态 {value!r}；可用：{', '.join(FACTOR_STATUS_VALUES)}")
        return value


class FactorEvaluateRequest(BaseModel):
    """Ask for a professional evaluation of a stored factor.

    Defaults to the small static panel so a click answers in seconds; ``full`` is
    the deliberate production-grade re-run over the windowed panel (minutes).
    """

    dataset: str = Field("debug", description="debug (small, fast) | full (windowed panel)")
    quantiles: int = Field(5, ge=2, le=10, description="Quantile buckets")
    periods: list[int] = Field(
        default_factory=lambda: [1, 5, 10], description="Forward periods in trading days"
    )
    window_days: int | None = Field(
        None, ge=20, le=1000, description="Trailing window for dataset=full (default 250)"
    )

    @field_validator("dataset")
    @classmethod
    def dataset_must_be_known(cls, value: str) -> str:
        if value not in ("debug", "full"):
            raise ValueError("dataset 只能是 debug 或 full")
        return value
