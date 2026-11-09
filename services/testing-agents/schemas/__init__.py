import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator
import jsonschema
from referencing import Registry, Resource

# Reuse existing Application Intelligence contracts without duplicating logic
_APP_INTEL_ROOT = Path(__file__).resolve().parents[2] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.models.technology import Evidence, Technology
from src.models.service import Service
from src.models.dependency import Dependency
from src.models.api import Api
from src.models.architecture import ArchitectureGraph, GraphNode, GraphEdge
from src.models.risk import RiskFinding
from src.models.test_candidate import TestCandidate
from src.models.experiment import (
    AbortCondition,
    BlastRadius,
    ExperimentSpecification,
    Fault,
    Rollback,
    Safety,
    SteadyState,
    Target,
)
from src.models.safety import SafetyDecision
from src.models.application import ApplicationModel

SCHEMA_VERSION = "1.0.0"

VALID_TEST_TYPES = (
    "availability",
    "latency",
    "dependency_resilience",
    "api_resilience",
    "resource_exhaustion",
    "failover",
    "degradation",
    "workflow_resilience",
)

VALID_PRIORITIES = ("low", "medium", "high", "critical")


class TestingAgentError(Exception):
    """Base exception for Testing Agents subsystem."""


class InvalidInputError(TestingAgentError):
    """Raised when input models or parameters are invalid."""


class EvidenceTraceabilityError(TestingAgentError):
    """Raised when a test case or plan lacks verifiable source evidence."""


class SchemaValidationError(TestingAgentError):
    """Raised when an input or output fails shared JSON Schema validation."""


class SafetyViolationError(TestingAgentError):
    """Raised when an agent or AI provider attempts to authorize execution or bypass safety."""


class TestStep(BaseModel):
    __test__ = False
    step_number: int = Field(ge=1)
    phase: Literal["steady_state_check", "stimulus_plan", "observation", "recovery_verification"]
    action: str = Field(min_length=1)
    expected_observation: str = Field(min_length=1)


class PriorityBreakdown(BaseModel):
    total_score: float = Field(ge=0.0, le=100.0)
    priority_band: Literal["low", "medium", "high", "critical"]
    risk_score: float = Field(ge=0.0, le=1.0)
    severity_score: float = Field(ge=0.0, le=1.0)
    dependency_criticality_score: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=1)
    factors: List[str] = Field(default_factory=list)


class TestCase(BaseModel):
    __test__ = False
    test_case_id: str = Field(min_length=1)
    schema_version: str = Field(default=SCHEMA_VERSION, min_length=1)
    application_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    target_name: str = Field(min_length=1)
    test_type: Literal[
        "availability",
        "latency",
        "dependency_resilience",
        "api_resilience",
        "resource_exhaustion",
        "failover",
        "degradation",
        "workflow_resilience",
    ]
    title: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    expected_failure_mode: str = Field(min_length=1)
    status: Literal["draft", "requires_review"] = "draft"
    mode: Literal["plan_only"] = "plan_only"
    execution_authorized: bool = False
    requires_safety_decision: bool = True
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    priority_score: float = Field(default=0.0, ge=0.0, le=100.0)
    rank: Optional[int] = Field(default=None, ge=1)
    priority_breakdown: PriorityBreakdown
    confidence: float = Field(ge=0.0, le=1.0)
    preconditions: List[str] = Field(default_factory=list)
    test_steps: List[TestStep] = Field(min_length=1)
    assertions: List[str] = Field(min_length=1)
    required_capabilities: List[str] = Field(default_factory=list)
    related_risk_ids: List[str] = Field(default_factory=list)
    related_experiment_ids: List[str] = Field(default_factory=list)
    evidence: List[Evidence] = Field(min_length=1)
    evidence_reasoning: str = Field(min_length=1)
    generation_source: Literal["deterministic_candidate", "coverage_gap_synthesis", "ai_suggestion"] = (
        "deterministic_candidate"
    )
    provider_id: str = Field(default="deterministic-baseline-v1", min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("execution_authorized")
    @classmethod
    def _enforce_no_execution_authorization(cls, v: bool) -> bool:
        if v is not False:
            raise SafetyViolationError(
                "Testing agents and AI providers cannot authorize test execution (execution_authorized must be False)."
            )
        return False

    @field_validator("requires_safety_decision")
    @classmethod
    def _enforce_requires_safety_decision(cls, v: bool) -> bool:
        if v is not True:
            raise SafetyViolationError(
                "All generated test cases must require Safety & Policy Engine evaluation (requires_safety_decision must be True)."
            )
        return True


class DimensionCoverage(BaseModel):
    dimension: Literal["service", "dependency", "api", "workflow"]
    total: int = Field(ge=0)
    covered: int = Field(ge=0)
    uncovered: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    covered_ids: List[str] = Field(default_factory=list)
    uncovered_ids: List[str] = Field(default_factory=list)


class CoverageGap(BaseModel):
    gap_id: str = Field(min_length=1)
    dimension: Literal["service", "dependency", "api", "workflow"]
    target_id: str = Field(min_length=1)
    target_name: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]
    reason: str = Field(min_length=1)
    suggested_test_type: Literal[
        "availability",
        "latency",
        "dependency_resilience",
        "api_resilience",
        "resource_exhaustion",
        "failover",
        "degradation",
        "workflow_resilience",
    ]
    evidence: List[Evidence] = Field(min_length=1)


class CoverageReport(BaseModel):
    application_id: str = Field(min_length=1)
    schema_version: str = Field(default=SCHEMA_VERSION, min_length=1)
    total_entities: int = Field(ge=0)
    covered_entities: int = Field(ge=0)
    uncovered_entities: int = Field(ge=0)
    overall_coverage_ratio: float = Field(ge=0.0, le=1.0)
    service_coverage: DimensionCoverage
    dependency_coverage: DimensionCoverage
    api_coverage: DimensionCoverage
    workflow_coverage: DimensionCoverage
    gaps: List[CoverageGap] = Field(default_factory=list)


class TestPlanSummary(BaseModel):
    __test__ = False
    total_test_cases: int = Field(ge=0)
    by_priority: Dict[str, int]
    by_test_type: Dict[str, int]
    deduplicated_count: int = Field(ge=0)
    total_risks_addressed: int = Field(ge=0)
    total_coverage_gaps: int = Field(ge=0)
    overall_coverage_ratio: float = Field(ge=0.0, le=1.0)


class TestPlan(BaseModel):
    __test__ = False
    plan_id: str = Field(min_length=1)
    schema_version: str = Field(default=SCHEMA_VERSION, min_length=1)
    application_id: str = Field(min_length=1)
    application_name: str = Field(min_length=1)
    status: Literal["draft", "requires_review"] = "draft"
    execution_authorized: bool = False
    safety_gate_status: Literal["pending_safety_engine"] = "pending_safety_engine"
    provider_id: str = Field(default="deterministic-baseline-v1", min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    summary: TestPlanSummary
    test_cases: List[TestCase] = Field(default_factory=list)
    coverage_report: CoverageReport
    evidence: List[Evidence] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("execution_authorized")
    @classmethod
    def _enforce_plan_not_authorized(cls, v: bool) -> bool:
        if v is not False:
            raise SafetyViolationError("TestPlan cannot authorize execution (execution_authorized must be False).")
        return False


class SchemaValidator:
    """
    Validates inputs and outputs against shared JSON schemas in packages/schemas/
    and services/testing-agents/schemas/.
    """

    def __init__(self) -> None:
        self.local_schema_dir = Path(__file__).resolve().parent
        self.shared_schema_dir = Path(__file__).resolve().parents[3] / "packages" / "schemas"
        self._schemas: Dict[str, Dict[str, Any]] = {}
        self.registry = self._build_registry()

    def _build_registry(self) -> Registry:
        registry = Registry()
        search_dirs = [d for d in (self.shared_schema_dir, self.local_schema_dir) if d.exists()]
        for directory in search_dirs:
            for schema_file in sorted(directory.glob("*.schema.json")):
                with open(schema_file, "r", encoding="utf-8") as f:
                    schema = json.load(f)
                self._schemas[schema_file.name] = schema
                resource = Resource.from_contents(schema)
                if "$id" in schema:
                    registry = registry.with_resource(uri=schema["$id"], resource=resource)
                registry = registry.with_resource(uri=schema_file.name, resource=resource)
        return registry

    def get_schema(self, schema_name: str) -> Dict[str, Any]:
        if schema_name not in self._schemas:
            raise SchemaValidationError(f"Schema '{schema_name}' not found in registry.")
        return self._schemas[schema_name]

    def validate(self, payload: Any, schema_name: str) -> None:
        if isinstance(payload, BaseModel):
            data = payload.model_dump(mode="json")
        elif isinstance(payload, dict):
            data = payload
        else:
            raise SchemaValidationError(f"Payload for '{schema_name}' must be a dict or Pydantic model.")

        schema = self.get_schema(schema_name)
        validator = jsonschema.Draft7Validator(schema, registry=self.registry)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        if errors:
            first = errors[0]
            loc = ".".join(str(p) for p in first.path) or "<root>"
            raise SchemaValidationError(
                f"Schema validation failed for '{schema_name}' at '{loc}': {first.message}"
            )

    def validate_test_case(self, test_case: TestCase) -> None:
        self.validate(test_case, "test-case.schema.json")

    def validate_coverage_report(self, report: CoverageReport) -> None:
        self.validate(report, "coverage-report.schema.json")

    def validate_test_plan(self, plan: TestPlan) -> None:
        self.validate(plan, "test-plan.schema.json")

    def validate_test_execution_result(self, result: Any) -> None:
        self.validate(result, "test-run.schema.json")


__all__ = [
    "SCHEMA_VERSION",
    "VALID_TEST_TYPES",
    "VALID_PRIORITIES",
    "TestingAgentError",
    "InvalidInputError",
    "EvidenceTraceabilityError",
    "SchemaValidationError",
    "SafetyViolationError",
    "Evidence",
    "Technology",
    "Service",
    "Dependency",
    "Api",
    "ArchitectureGraph",
    "GraphNode",
    "GraphEdge",
    "RiskFinding",
    "TestCandidate",
    "ExperimentSpecification",
    "SafetyDecision",
    "ApplicationModel",
    "TestStep",
    "PriorityBreakdown",
    "TestCase",
    "DimensionCoverage",
    "CoverageGap",
    "CoverageReport",
    "TestPlanSummary",
    "TestPlan",
    "SchemaValidator",
]
