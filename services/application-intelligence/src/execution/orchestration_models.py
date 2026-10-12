from pydantic import BaseModel, Field
from typing import Optional, List
from ..models.application import ApplicationModel
from ..models.experiment import ExperimentSpecification
from ..models.safety import SafetyDecision
from ..models.experiment_run import ExperimentRun
from .adapters.plan import ExecutionPlan
from .adapters.result import ExecutionResult

class OrchestrationRequest(BaseModel):
    application_model: ApplicationModel
    experiment_specification: ExperimentSpecification
    safety_decision: SafetyDecision
    experiment_run: ExperimentRun
    mode: str = "dry_run"

class OrchestrationResponse(BaseModel):
    status: str # completed, rejected, failed
    run_id: str
    experiment_id: str
    safety_decision_id: str
    mode: str
    adapter_id: Optional[str] = None
    plan: Optional[ExecutionPlan] = None
    result: Optional[ExecutionResult] = None
    errors: List[str] = Field(default_factory=list)
