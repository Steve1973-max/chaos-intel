from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

try:
    from ..schemas import SchemaValidator
    from .sandbox import SecretRedactor
except ImportError:
    from schemas import SchemaValidator  # type: ignore[no-redef]
    from execution.sandbox import SecretRedactor  # type: ignore[no-redef]


ExecutionStatus = Literal["passed", "failed", "skipped", "timed_out", "cancelled", "unknown"]
StepStage = Literal["precondition", "step", "postcondition"]
EvidenceType = Literal[
    "http_trace",
    "screenshot",
    "console_log",
    "network_log",
    "step_trace",
    "assertion_log",
]


class ExecutionErrorDetail(BaseModel):
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    failed_step_number: Optional[int] = None
    failed_stage: Optional[str] = None
    failed_target: Optional[str] = None
    outcome_uncertain: bool = False


class ExecutionEvidenceReference(BaseModel):
    evidence_id: str = Field(min_length=1)
    type: EvidenceType
    uri: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    redacted_metadata: Dict[str, Any] = Field(default_factory=dict)


class StepExecutionResult(BaseModel):
    step_number: int = Field(ge=1)
    step_name: str = Field(min_length=1)
    stage: StepStage = "step"
    status: ExecutionStatus
    started_at: str = Field(min_length=1)
    ended_at: str = Field(min_length=1)
    duration_ms: float = Field(ge=0.0)
    latency_ms: Optional[float] = Field(default=None, ge=0.0)
    details: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[ExecutionErrorDetail] = None
    evidence_refs: List[str] = Field(default_factory=list)


class TestExecutionResult(BaseModel):
    __test__ = False
    execution_id: str = Field(min_length=1)
    test_case_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    status: ExecutionStatus
    started_at: str = Field(min_length=1)
    ended_at: str = Field(min_length=1)
    duration_ms: float = Field(ge=0.0)
    correlation_id: str = Field(min_length=1)
    cleanup_completed: bool = True
    step_results: List[StepExecutionResult] = Field(default_factory=list)
    error_details: Optional[ExecutionErrorDetail] = None
    evidence_references: List[ExecutionEvidenceReference] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlanExecutionSummary(BaseModel):
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    timed_out: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    unknown: int = Field(ge=0)


class PlanExecutionReport(BaseModel):
    plan_execution_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    status: Literal["completed", "partial_failure", "failed", "cancelled", "rejected"]
    started_at: str = Field(min_length=1)
    ended_at: str = Field(min_length=1)
    duration_ms: float = Field(ge=0.0)
    summary: PlanExecutionSummary
    results: List[TestExecutionResult] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResultCollector:
    """
    Collects, normalizes, redacts credentials from, and schema-validates TestExecutionResults
    against the shared test-run.schema.json contract.
    """

    def __init__(self, schema_validator: Optional[SchemaValidator] = None) -> None:
        self.schema_validator = schema_validator or SchemaValidator()
        self._results: List[TestExecutionResult] = []

    def normalize_and_record(
        self, result: TestExecutionResult, validate_schema: bool = True
    ) -> TestExecutionResult:
        normalized = result.model_copy(deep=True)
        normalized.duration_ms = round(max(0.0, float(normalized.duration_ms)), 3)
        normalized.metadata = SecretRedactor.redact(normalized.metadata or {})

        if normalized.error_details:
            normalized.error_details.message = SecretRedactor.redact_string(normalized.error_details.message)

        for step in normalized.step_results:
            step.duration_ms = round(max(0.0, float(step.duration_ms)), 3)
            if step.latency_ms is not None:
                step.latency_ms = round(max(0.0, float(step.latency_ms)), 3)
            step.details = SecretRedactor.redact(step.details or {})
            if step.error:
                step.error.message = SecretRedactor.redact_string(step.error.message)

        for ev in normalized.evidence_references:
            ev.summary = SecretRedactor.redact_string(ev.summary)
            ev.redacted_metadata = SecretRedactor.redact(ev.redacted_metadata or {})

        if validate_schema:
            self.schema_validator.validate_test_execution_result(normalized)

        self._results.append(normalized)
        return normalized

    def get_results(self) -> List[TestExecutionResult]:
        return sorted(self._results, key=lambda r: (r.test_case_id, r.execution_id))

    @staticmethod
    def build_summary(results: List[TestExecutionResult]) -> PlanExecutionSummary:
        counts: Dict[str, int] = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "timed_out": 0,
            "cancelled": 0,
            "unknown": 0,
        }
        for res in results:
            counts[res.status] = counts.get(res.status, 0) + 1
        return PlanExecutionSummary(
            total=len(results),
            passed=counts["passed"],
            failed=counts["failed"],
            skipped=counts["skipped"],
            timed_out=counts["timed_out"],
            cancelled=counts["cancelled"],
            unknown=counts["unknown"],
        )

