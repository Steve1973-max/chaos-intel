from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

class SafetyCheck(BaseModel):
    check_id: str
    category: str
    status: str # pass, fail, warning, not_evaluated, requires_configuration
    severity: str # info, low, medium, high, critical
    message: str
    evidence: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SafetyDecision(BaseModel):
    decision_id: str
    experiment_id: str
    application_id: str
    decision: str # blocked, requires_configuration, requires_approval, approved
    allowed: bool
    checks: List[SafetyCheck] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    required_approvals: List[str] = Field(default_factory=list)
    required_conditions: List[str] = Field(default_factory=list)
    evaluated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    policy_version: str = "1.0.0"
    metadata: Dict[str, Any] = Field(default_factory=dict)
