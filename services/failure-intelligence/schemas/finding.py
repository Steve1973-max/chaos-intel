"""Failure intelligence findings, correlation, and root-cause schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from schemas.anomaly import Anomaly
from schemas.telemetry import StructuredLogEntry, TraceSpan

FailureCategory = Literal[
    "Infrastructure",
    "Network",
    "Application",
    "Database",
    "Dependency",
    "Configuration",
    "ResourceExhaustion",
    "Unknown",
]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CorrelatedFailureCluster(BaseModel):
    """Correlated cluster of anomalies, logs, spans, test failures, and chaos events."""

    cluster_id: str
    correlation_id: str
    time_window_start: str
    time_window_end: str
    primary_affected_service: str
    affected_services: List[str] = Field(default_factory=list)
    anomalies: List[Anomaly] = Field(default_factory=list)
    error_logs: List[StructuredLogEntry] = Field(default_factory=list)
    error_spans: List[TraceSpan] = Field(default_factory=list)
    test_failures: List[Dict[str, Any]] = Field(default_factory=list)
    chaos_events: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DependencyImpact(BaseModel):
    """Topological failure propagation analysis across services and workflows."""

    root_service_id: str
    directly_affected_services: List[str] = Field(default_factory=list)
    downstream_impacted_services: List[str] = Field(default_factory=list)
    impacted_apis: List[str] = Field(default_factory=list)
    cascading_failure: bool = False
    propagation_path: List[str] = Field(default_factory=list)
    blast_radius_score: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RootCauseHypothesis(BaseModel):
    """Probable root cause hypothesis.

    Explicitly differentiates inferred causation from observed correlation.
    """

    hypothesis_id: str
    probable_root_cause_service: str
    failure_category: FailureCategory
    title: str
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)
    is_causation_proven: bool = False  # Strictly False: correlation is not proven causation
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    conflicting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

