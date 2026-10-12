from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

class ExecutionResult(BaseModel):
    result_id: str
    run_id: str
    plan_id: str
    adapter_id: str
    status: str # planned, prepared, executed, observed, aborted, rolled_back, recovered, completed, failed
    mode: str = "dry_run"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
