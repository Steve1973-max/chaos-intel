"""Testing agents request and response schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TestPlanGenerateRequest(BaseModel):
    """Request to generate a test plan for an application."""

    application_id: str
    options: Dict[str, Any] = Field(default_factory=dict)


class TestPlanResponse(BaseModel):
    """Generated test plan metadata and cases."""

    plan_id: str
    application_id: str
    created_at: str
    test_cases_count: int
    test_cases: List[Dict[str, Any]]
    coverage_summary: Dict[str, Any] = Field(default_factory=dict)


class TestExecutionRequest(BaseModel):
    """Request to initiate test execution."""

    plan_id: str
    application_id: str
    options: Dict[str, Any] = Field(default_factory=dict)


class TestExecutionResponse(BaseModel):
    """Test execution status and result summary."""

    execution_id: str
    plan_id: str
    application_id: str
    status: str  # queued, running, passed, failed, cancelled
    duration_ms: float = 0.0
    passed_count: int = 0
    failed_count: int = 0
    step_results: List[Dict[str, Any]] = Field(default_factory=list)

