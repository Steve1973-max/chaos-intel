from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

class ApprovalModel(BaseModel):
    required: bool
    status: str = "not_required" # not_required, pending, approved, rejected
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    reference: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PreflightCheck(BaseModel):
    check_id: str
    status: str
    message: str

class PreflightModel(BaseModel):
    status: str = "pending" # pending, passed, failed
    checks: List[PreflightCheck] = Field(default_factory=list)
    evaluated_at: Optional[str] = None
    errors: List[str] = Field(default_factory=list)

class ExecutionModel(BaseModel):
    status: str = "pending" # pending, running, completed, failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class AbortModel(BaseModel):
    requested: bool = False
    requested_at: Optional[str] = None
    requested_by: Optional[str] = None
    reason: Optional[str] = None
    source: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RollbackRunModel(BaseModel):
    required: bool
    status: str = "not_required" # not_required, pending, running, completed, failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    strategy: Optional[str] = None
    verification: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RecoveryModel(BaseModel):
    required: bool
    status: str = "not_required" # pending, running, passed, failed, not_required
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    checks: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class EvidenceRef(BaseModel):
    evidence_id: str
    type: str
    location: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ErrorModel(BaseModel):
    type: str
    message: str
    traceback: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RequiredConditionModel(BaseModel):
    condition_id: str
    description: str
    status: str = "pending" # pending, satisfied, failed
    satisfied_at: Optional[str] = None
    evidence: Optional[str] = None

class ExperimentRun(BaseModel):
    run_id: str
    experiment_id: str
    application_id: str
    safety_decision_id: str
    state: str = "CREATED"
    version: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    current_phase: Optional[str] = None
    approval: ApprovalModel = Field(default_factory=lambda: ApprovalModel(required=False))
    preflight: PreflightModel = Field(default_factory=PreflightModel)
    execution: ExecutionModel = Field(default_factory=ExecutionModel)
    abort: AbortModel = Field(default_factory=AbortModel)
    rollback: RollbackRunModel = Field(default_factory=lambda: RollbackRunModel(required=False))
    recovery: RecoveryModel = Field(default_factory=lambda: RecoveryModel(required=False))
    required_conditions: List[RequiredConditionModel] = Field(default_factory=list)
    evidence_refs: List[EvidenceRef] = Field(default_factory=list)
    error: Optional[ErrorModel] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    lifecycle_version: str = "1.0.0"
