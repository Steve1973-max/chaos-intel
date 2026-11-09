"""Shared models, safety errors, and settings for the CHAOS-INTEL Phase 3C Chaos Engine."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, Field, field_validator

from blast_radius import BlastRadiusAssessment
from experiment_observer import ExperimentObservationRecord
from rollback_manager import RollbackOutcome

ExecutionMode = Literal["dry_run", "live"]
ExperimentVerdict = Literal["passed", "failed", "aborted", "cancelled", "rejected", "unresolved"]

# Phase 3C hard safety invariant. Intentionally a module constant, not a setting:
# no configuration, authorization, or adapter can enable live fault execution.
LIVE_EXECUTION_ENABLED: bool = False

# Identities that may never act as a human approver (AI agents and the engine itself).
RESERVED_NON_HUMAN_APPROVERS: Set[str] = {
    "system",
    "chaos-engine",
    "chaos_engine",
    "ai",
    "agent",
    "llm",
    "testing-agent",
    "auto",
    "automation",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChaosEngineError(Exception):
    """Base class for chaos engine safety errors."""


class LiveExecutionDisabledError(ChaosEngineError):
    """Raised when live fault execution is requested; live execution is disabled in Phase 3C."""


class LiveAuthorizationRequiredError(ChaosEngineError):
    """Raised when a live experiment is requested without explicit per-experiment authorization."""


class AdapterNotPermittedError(ChaosEngineError):
    """Raised when an adapter is unsafe (live-capable) or incompatible with the experiment."""


class TargetNotAuthorizedError(ChaosEngineError):
    """Raised when a target or environment is outside the approved execution scope."""


class ChaosEngineSettings(BaseModel):
    """Engine-level guardrails layered on top of the Safety & Policy Engine (never weaker)."""

    authorized_environments: Set[str] = Field(default_factory=lambda: {"development", "test", "staging"})
    authorized_target_ids: Optional[Set[str]] = None  # None = any target that exists in the ApplicationModel
    max_fault_duration_seconds: int = Field(default=300, ge=1, le=300)
    max_observation_windows: int = Field(default=10, ge=1, le=100)

    @field_validator("authorized_environments")
    @classmethod
    def _never_production(cls, v: Set[str]) -> Set[str]:
        if "production" in v:
            raise ValueError("Production can never be an authorized chaos environment.")
        return v


class LiveExecutionAuthorization(BaseModel):
    """Explicit per-experiment live authorization record (required, but still insufficient in Phase 3C)."""

    authorization_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved: bool = True


class ApprovalGrant(BaseModel):
    """Human safety approval for a specific experiment, plus evidence for required conditions."""

    experiment_id: str = Field(min_length=1)
    approver: str = Field(min_length=1)
    approved: bool = True
    reference: Optional[str] = None
    condition_evidence: Dict[str, str] = Field(default_factory=dict)  # keyed by condition description

    @field_validator("approver")
    @classmethod
    def _human_approver_only(cls, v: str) -> str:
        if v.strip().lower() in RESERVED_NON_HUMAN_APPROVERS:
            raise ValueError(f"Approver '{v}' is a reserved non-human identity and cannot approve experiments.")
        return v


class ExperimentCancellationToken:
    """Thread-safe cooperative cancellation / emergency-abort signal for a single experiment."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._emergency = False
        self._reason: Optional[str] = None
        self._requested_at: Optional[str] = None

    def cancel(self, reason: str = "Experiment cancelled by operator.", emergency: bool = False) -> None:
        with self._lock:
            if not self._cancelled:
                self._reason = reason
                self._requested_at = utcnow_iso()
            self._cancelled = True
            self._emergency = self._emergency or emergency

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def is_emergency(self) -> bool:
        with self._lock:
            return self._emergency

    @property
    def reason(self) -> Optional[str]:
        with self._lock:
            return self._reason

    @property
    def requested_at(self) -> Optional[str]:
        with self._lock:
            return self._requested_at


class AbortRecord(BaseModel):
    triggered: bool = False
    source: Optional[str] = None  # safety_threshold, emergency, cancellation, uncertain_injection, observation_error
    reason: Optional[str] = None
    triggered_conditions: List[Dict[str, Any]] = Field(default_factory=list)
    adapter_abort_error: Optional[str] = None


class ChaosExperimentReport(BaseModel):
    """Final, evidence-backed report for a chaos experiment run."""

    report_id: str
    run_id: str
    experiment_id: str
    application_id: str
    correlation_id: str
    mode: ExecutionMode
    live_execution: bool = False
    adapter_id: Optional[str] = None
    verdict: ExperimentVerdict
    hypothesis_held: Optional[bool] = None
    final_lifecycle_state: str
    recovery_classification: Optional[str] = None
    outcome_uncertain: bool = False
    automatic_replay_attempted: bool = False
    fault_type: str
    target_id: str
    duration_seconds: int
    risk_classification: Optional[str] = None
    safety_decision_id: str
    safety_decision: str
    validation_errors: List[str] = Field(default_factory=list)
    validation_warnings: List[str] = Field(default_factory=list)
    blast_radius: Optional[BlastRadiusAssessment] = None
    abort: AbortRecord = Field(default_factory=AbortRecord)
    rollback: Optional[RollbackOutcome] = None
    observation: Optional[ExperimentObservationRecord] = None
    adapter_invocations: Dict[str, int] = Field(default_factory=dict)
    lifecycle_phases_completed: List[str] = Field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    audit_events: List[Dict[str, Any]] = Field(default_factory=list)
    declarative_manifests: Dict[str, Any] = Field(default_factory=dict)
    run_schema_errors: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=utcnow_iso)

