from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from .technology import Evidence

class Target(BaseModel):
    type: str
    id: str
    name: str

class Fault(BaseModel):
    type: str
    method: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    purpose: Optional[str] = None

class BlastRadius(BaseModel):
    scope: str
    max_affected_components: int

class SteadyState(BaseModel):
    required: bool
    checks: List[str] = Field(default_factory=list)

class AbortCondition(BaseModel):
    metric: str
    operator: str
    threshold: Any
    action: str = "abort"
    requires_configuration: bool = False

class Rollback(BaseModel):
    strategy: str
    automatic: bool
    verification_required: bool = False

class Safety(BaseModel):
    requires_approval: bool = True
    environment_required: Optional[str] = None
    reversible: bool = True
    rollback_required: bool = True
    production_allowed: bool = False

class ExperimentSpecification(BaseModel):
    __test__ = False
    experiment_id: str
    application_id: str
    candidate_ids: List[str]
    name: str
    hypothesis: str
    status: str
    target: Target
    fault: Fault
    duration_seconds: int
    blast_radius: BlastRadius
    steady_state: SteadyState
    observations: List[str] = Field(default_factory=list)
    abort_conditions: List[AbortCondition] = Field(default_factory=list)
    rollback: Rollback
    prerequisites: List[str] = Field(default_factory=list)
    safety: Safety
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
