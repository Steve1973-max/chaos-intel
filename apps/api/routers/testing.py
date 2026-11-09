"""Testing router: test planning, test case generation, execution, and reports."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.dependencies import (
    get_app_intel_client,
    get_correlation_id,
    get_job_queue,
    get_testing_agents_client,
)
from apps.api.middleware.auth import require_role, UserContext
from apps.api.schemas.common import PaginatedResponse
from apps.api.schemas.testing import (
    TestExecutionRequest,
    TestExecutionResponse,
    TestPlanGenerateRequest,
    TestPlanResponse,
)
from packages.clients.app_intel_client import ApplicationIntelligenceClient
from packages.clients.testing_agents_client import TestingAgentsClient
from workers.queue import JobQueue

router = APIRouter(prefix="/testing", tags=["Testing Agents"])

_test_plans: Dict[str, Dict[str, Any]] = {}
_test_executions: Dict[str, Dict[str, Any]] = {}


@router.post("/plans/generate", response_model=TestPlanResponse, status_code=status.HTTP_201_CREATED)
async def generate_test_plan(
    payload: TestPlanGenerateRequest,
    correlation_id: str = Depends(get_correlation_id),
    client: TestingAgentsClient = Depends(get_testing_agents_client),
    app_intel: ApplicationIntelligenceClient = Depends(get_app_intel_client),
    user: UserContext = Depends(require_role("operator")),
) -> TestPlanResponse:
    """Generate structured test plan for application."""
    # Look up analyzed application model if available; fallback to lightweight wrapper
    real_app = await app_intel.get_application(payload.application_id, correlation_id=correlation_id)

    if real_app is None:
        class _MockApp:
            application_id = payload.application_id
            name = "App"
            services = []
            apis = []
            dependencies = []
            risks = []
            architecture = None
        target_app = _MockApp()
    else:
        target_app = real_app

    plan = await client.generate_test_plan(target_app, correlation_id=correlation_id, options=payload.options)
    plan_id = getattr(plan, "plan_id", f"plan-{uuid.uuid4().hex[:8]}")
    cases = [c.model_dump() if hasattr(c, "model_dump") else dict(c) for c in getattr(plan, "test_cases", [])]

    record = {
        "plan_id": plan_id,
        "application_id": payload.application_id,
        "created_at": correlation_id,
        "test_cases_count": len(cases),
        "test_cases": cases,
        "coverage_summary": getattr(plan, "coverage_summary", {}),
    }
    _test_plans[plan_id] = record
    return TestPlanResponse(**record)


@router.get("/plans/{plan_id}", response_model=TestPlanResponse)
async def get_test_plan(
    plan_id: str,
    correlation_id: str = Depends(get_correlation_id),
    user: UserContext = Depends(require_role("viewer")),
) -> TestPlanResponse:
    """Retrieve test plan by ID."""
    plan = _test_plans.get(plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Test plan '{plan_id}' not found")
    return TestPlanResponse(**plan)


@router.post("/executions", response_model=TestExecutionResponse, status_code=status.HTTP_202_ACCEPTED)
async def initiate_test_execution(
    payload: TestExecutionRequest,
    correlation_id: str = Depends(get_correlation_id),
    queue: JobQueue = Depends(get_job_queue),
    user: UserContext = Depends(require_role("operator")),
) -> TestExecutionResponse:
    """Initiate asynchronous test execution for approved test plan."""
    exec_id = f"exec-{uuid.uuid4().hex[:8]}"
    record = {
        "execution_id": exec_id,
        "plan_id": payload.plan_id,
        "application_id": payload.application_id,
        "status": "queued",
        "duration_ms": 0.0,
        "passed_count": 0,
        "failed_count": 0,
        "step_results": [],
    }
    _test_executions[exec_id] = record

    await queue.enqueue(
        task_name="execute_tests",
        payload={"execution_id": exec_id, "plan_id": payload.plan_id, "application_id": payload.application_id},
        correlation_id=correlation_id,
    )
    return TestExecutionResponse(**record)


@router.get("/executions/{execution_id}", response_model=TestExecutionResponse)
async def get_test_execution(
    execution_id: str,
    correlation_id: str = Depends(get_correlation_id),
    user: UserContext = Depends(require_role("viewer")),
) -> TestExecutionResponse:
    """Retrieve test execution status and results."""
    rec = _test_executions.get(execution_id)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Execution '{execution_id}' not found")
    return TestExecutionResponse(**rec)


@router.get("/executions", response_model=PaginatedResponse[TestExecutionResponse])
async def list_test_executions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    correlation_id: str = Depends(get_correlation_id),
    user: UserContext = Depends(require_role("viewer")),
) -> PaginatedResponse[TestExecutionResponse]:
    """Retrieve paginated list of test executions."""
    all_execs = [TestExecutionResponse(**e) for e in _test_executions.values()]
    total = len(all_execs)
    sliced = all_execs[offset : offset + limit]
    return PaginatedResponse(
        items=sliced,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )
