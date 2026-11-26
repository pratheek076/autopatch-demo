"""Pydantic schemas — shared data models across all agents."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class FailureType(str, Enum):
    FLAKY_TEST = "flaky_test"
    REGRESSION = "regression"
    DEPENDENCY = "dependency"
    INFRA = "infra"
    UNKNOWN = "unknown"


class PipelineFailure(BaseModel):
    """Represents a detected CI/CD pipeline failure."""
    run_id: str
    repo: str
    branch: str
    commit_sha: str
    workflow_name: str
    failed_step: str
    logs: str
    failure_type: FailureType = FailureType.UNKNOWN
    diagnosis_confidence: float = 0.0
    triggered_at: str


class CandidatePatch(BaseModel):
    """A patch proposed by the Patch Agent."""
    failure_id: str
    file_path: str
    original_code: str
    patched_code: str
    explanation: str
    lines_changed: int
    touches_test_files: bool = False
    introduces_secrets: bool = False
    coverage_delta: float = 0.0  # estimated, negative = coverage dropped


class GuardrailVerdict(BaseModel):
    """Result from the formal guardrail layer."""
    passed: bool
    z3_result: dict = Field(default_factory=dict)   # Z3 invariant check results
    opa_result: dict = Field(default_factory=dict)   # OPA policy check results
    violations: list[str] = Field(default_factory=list)
    explanation: str = ""


class AgentState(BaseModel):
    """Shared state passed through the LangGraph agent graph."""
    failure: Optional[PipelineFailure] = None
    patch: Optional[CandidatePatch] = None
    guardrail_verdict: Optional[GuardrailVerdict] = None
    pr_url: Optional[str] = None
    issue_url: Optional[str] = None
    status: str = "pending"   # pending | diagnosed | patched | verified | rejected | done


class WebhookPayload(BaseModel):
    """Incoming GitHub Actions webhook payload (simplified)."""
    action: str
    workflow_run: dict
