"""Anomaly detection models and schemas for CHAOS-INTEL Phase 4."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

AnomalySeverity = Literal["info", "low", "medium", "high", "critical"]
AnomalyMethod = Literal[
    "threshold",
    "moving_average",
    "statistical_zscore",
    "statistical_iqr",
    "latency_spike",
    "error_rate_increase",
    "availability_degradation",
    "resource_saturation",
]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Anomaly(BaseModel):
    """Structured, evidence-backed anomaly detection record."""

    anomaly_id: str
    timestamp: str = Field(default_factory=utcnow_iso)
    affected_service: str
    metric: str
    observed_value: float
    baseline_value: float
    deviation_percentage: float = 0.0
    severity: AnomalySeverity
    detection_method: AnomalyMethod
    evidence_references: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

