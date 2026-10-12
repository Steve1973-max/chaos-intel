from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from ...models.experiment_run import ExperimentRun
from ...models.experiment import ExperimentSpecification
from ...models.safety import SafetyDecision
from ...models.application import ApplicationModel

class ExecutionContext(BaseModel):
    run: ExperimentRun
    experiment: ExperimentSpecification
    safety_decision: SafetyDecision
    application_model: ApplicationModel
    mode: str = "dry_run"
    adapter_id: str
    correlation_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
