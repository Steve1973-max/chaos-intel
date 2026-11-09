"""Unified Experiment Analysis and Failure Intelligence Report schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from schemas.anomaly import Anomaly
from schemas.finding import DependencyImpact, RootCauseHypothesis
from schemas.recommendation import ActionableRecommendation


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UnifiedExperimentAnalysis(BaseModel):
    """Unified comprehensive failure intelligence report for an experiment or test run."""

    analysis_id: str
    experiment_id: str
    application_id: str
    correlation_id: str
    generated_at: str = Field(default_factory=utcnow_iso)
    baseline_health: Dict[str, Any] = Field(default_factory=dict)
    observed_anomalies: List[Anomaly] = Field(default_factory=list)
    affected_services: List[str] = Field(default_factory=list)
    failure_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    dependency_impact: Optional[DependencyImpact] = None
    probable_root_causes: List[RootCauseHypothesis] = Field(default_factory=list)
    recovery_behavior: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[ActionableRecommendation] = Field(default_factory=list)
    evidence_chain: List[Dict[str, Any]] = Field(default_factory=list)
    methodology_statement: str = (
        "Analysis performed using deterministic temporal-topological correlation. "
        "Correlations are presented as probable root-cause hypotheses with confidence ratings, "
        "not proven physical causation. Inferred causes are strictly distinguished from directly observed facts."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

