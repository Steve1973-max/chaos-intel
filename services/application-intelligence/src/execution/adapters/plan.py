from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

class PlanStep(BaseModel):
    step_id: str
    name: str
    order: int
    action: str
    status: str = "planned"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ExecutionPlan(BaseModel):
    plan_id: str
    run_id: str
    experiment_id: str
    application_id: str
    adapter_id: str
    adapter_version: str
    fault_type: str
    target_type: str
    target_id: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    required_capabilities: List[str] = Field(default_factory=list)
    safety_decision_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mode: str = "dry_run" # dry_run, live
    steps: List[PlanStep] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
