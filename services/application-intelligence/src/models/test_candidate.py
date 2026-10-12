from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from .technology import Evidence

class TestCandidate(BaseModel):
    __test__ = False
    candidate_id: str
    application_id: str
    target_type: str
    target_id: str
    test_type: str # availability, latency, dependency_resilience, api_resilience, resource_exhaustion, failover, degradation, workflow_resilience
    title: str
    hypothesis: str
    reason: str
    expected_failure_mode: str
    priority: str # low, medium, high, critical
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    prerequisites: List[str] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    related_risk_ids: List[str] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    suggested_observations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
