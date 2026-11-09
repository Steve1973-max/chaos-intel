"""Failure intelligence analysis schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FailureAnalysisRequest(BaseModel):
    """Payload to trigger failure intelligence analysis on an experiment."""

    application_id: str
    chaos_report_id: Optional[str] = None
    execution_ids: List[str] = Field(default_factory=list)


class FailureAnalysisResponse(BaseModel):
    """Unified failure intelligence report."""

    analysis_id: str
    application_id: str
    correlation_id: str
    anomalies_count: int
    probable_root_causes: List[Dict[str, Any]]
    recommendations_count: int
    recovery_status: str


class RecommendationListResponse(BaseModel):
    """List of actionable resilience recommendations."""

    total: int
    recommendations: List[Dict[str, Any]]

