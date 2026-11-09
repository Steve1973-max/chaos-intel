"""Distributed orchestration workflow schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PipelineTriggerRequest(BaseModel):
    """Payload to trigger the complete 10-step distributed orchestration workflow."""

    source_path: str = Field(..., min_length=1)
    application_name: str = Field(..., min_length=1)
    idempotency_key: Optional[str] = None
    approved_by: Optional[str] = None
    approval_grant_id: Optional[str] = None
    experiment_override: Optional[Dict[str, Any]] = None


class PipelineJobStatusResponse(BaseModel):
    """Pipeline execution status, artifacts, and timeline."""

    job_id: str
    status: str  # queued, running, completed, failed, cancelled, dead_letter
    correlation_id: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

