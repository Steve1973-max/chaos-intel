"""Actionable recommendation models for CHAOS-INTEL Phase 4."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

RecommendationPriority = Literal["critical", "high", "medium", "low"]
RecommendationCategory = Literal[
    "resilience",
    "capacity",
    "timeout_tuning",
    "circuit_breaker",
    "retry_policy",
    "redundancy",
    "configuration",
    "database_tuning",
]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActionableRecommendation(BaseModel):
    """Actionable recommendation backed by concrete evidence references."""

    recommendation_id: str
    category: RecommendationCategory
    priority: RecommendationPriority
    title: str
    description: str
    target_service: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    remediation_steps: List[str] = Field(default_factory=list)
    estimated_risk_reduction: str = "medium"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)

