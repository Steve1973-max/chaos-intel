"""Application registration, analysis, and discovery schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ApplicationRegisterRequest(BaseModel):
    """Payload to register an application directory or repository."""

    name: str = Field(..., min_length=1, max_length=255)
    source_type: str = Field("directory", pattern="^(directory|archive|git)$")
    source_location: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApplicationResponse(BaseModel):
    """Registered application summary."""

    application_id: str
    name: str
    source_type: str
    source_location: str
    status: str
    registered_at: str
    services_count: int = 0
    apis_count: int = 0
    technologies: List[str] = Field(default_factory=list)


class ArchitectureGraphResponse(BaseModel):
    """Architecture dependency graph."""

    application_id: str
    node_count: int
    edge_count: int
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


class RiskAssessmentResponse(BaseModel):
    """Architectural risk findings."""

    application_id: str
    risk_score: float
    findings_count: int
    findings: List[Dict[str, Any]]

