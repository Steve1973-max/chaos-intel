from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from .technology import Evidence

class RiskFinding(BaseModel):
    risk_id: str
    application_id: str
    category: str # architecture, dependency, availability, api, infrastructure, configuration
    risk_type: str
    severity: str # info, low, medium, high, critical
    title: str
    description: str
    target_type: str
    target_id: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)
    indicators: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
