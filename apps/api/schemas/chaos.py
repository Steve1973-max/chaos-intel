"""Chaos experiment request and response schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ChaosExperimentCreateRequest(BaseModel):
    """Payload to create and validate a controlled chaos experiment."""

    name: str
    application_id: str
    target_service_id: str
    fault_type: str
    environment: str = "staging"
    duration_seconds: int = Field(30, ge=5, le=300)
    safety_decision_id: str = "sec-01"
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ChaosExperimentResponse(BaseModel):
    """Created chaos experiment specification."""

    experiment_id: str
    name: str
    application_id: str
    target_service_id: str
    fault_type: str
    environment: str
    duration_seconds: int
    status: str  # created, validated, approved, rejected
    requires_approval: bool = True


class ChaosApprovalRequest(BaseModel):
    """Payload for human approval grant."""

    approved_by: str = Field(..., min_length=1)
    grant_id: str = Field(..., min_length=1)
    notes: Optional[str] = None


class ChaosExecutionRequest(BaseModel):
    """Payload to initiate a controlled experiment run."""

    experiment_id: str
    application_id: str
    dry_run: bool = True  # Strict safeguard: Live execution is disabled


class ChaosReportResponse(BaseModel):
    """Chaos experiment run report."""

    run_id: str
    experiment_id: str
    verdict: str  # DRY_RUN_VERIFIED, SUCCESS, RECOVERY_DEGRADED, ABORTED
    dry_run: bool
    live_execution: bool = False
    fault_type: str
    target_id: str
    recovery_status: str
    timeline: List[Dict[str, Any]] = Field(default_factory=list)

