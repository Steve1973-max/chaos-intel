"""Telemetry ingestion schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TelemetryIngestRequest(BaseModel):
    """Payload to ingest normalized telemetry, logs, and trace spans."""

    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    logs: List[Dict[str, Any]] = Field(default_factory=list)
    spans: List[Dict[str, Any]] = Field(default_factory=list)


class TelemetryIngestResponse(BaseModel):
    """Ingestion confirmation."""

    status: str
    metrics_count: int
    logs_count: int
    spans_count: int
    correlation_id: str

