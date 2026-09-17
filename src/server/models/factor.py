"""Pydantic models for the Factor Board endpoints.

The response shapes are declared rather than left as bare dicts so the OpenAPI
document is the contract the web client codes against: the detection page reads
``stages`` for its progress list, ``findings`` for the IC panel, and ``verdict``
for the headline, and each of those has to keep its field names.
"""

from typing import Any, List, Optional

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
    templates: List[FactorTemplate]


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
    elapsed_sec: Optional[float] = None


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
    stages: List[DetectionStage] = Field(default_factory=list)
    findings: dict[str, Any] = Field(default_factory=dict)
    verdict: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    error_kind: str = ""


class DetectionListResponse(BaseModel):
    runs: List[DetectionRunResponse]


class FactorMinerHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    configured: bool
    reachable: bool
    url: str = ""
